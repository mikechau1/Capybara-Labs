"""How an answer's text is written and displayed. Card M3-04 owns this file; the chat page
(card M3-08) renders what it produces.

A model's reply is never shown as it came. The answer step (chat/answering.py) cleans it
(`clean`), splits it into code and text (`segments`), checks the citation markers in the text
(`rewrite_citations`), and builds what the user sees with `to_markdown`. In that markdown:

- every ASCII punctuation character of the text is backslash-escaped (a backtick is written
  `&#96;`), so it shows as itself: no link, image, HTML, emphasis, heading, list, table or math
  can form, however the model nested, split or escaped it;
- an invisible word joiner (U+2060) breaks up the few places where a pattern would still form.
  Escaping is not enough there: Streamlit's renderer (react-markdown + remark-gfm) turns URLs,
  "www." addresses and emails into links, ":smile:"-style codes into emoji or icons and "->"
  into arrows, by searching the text after escapes are resolved. So a joiner goes after a ":"
  that is followed by a letter, digit, "/", "+", "-" or "_" (but not in 10:30 or 1:2), on both
  sides of "@", between "www" and ".", and between the characters of "<->=~" pairs.
  Everywhere else (5.2, 1,000, 10:30, C:\\Users, state-of-the-art) the copied text is the text;
- the only unescaped brackets are the citation markers `[n]` the answer step put there;
- code is written back with delimiters chosen here, so it shows as code and nothing in it is
  live. Markers inside code are code, not citations: the chat page must not link them.

So the stored answer is full of backslashes and some word joiners. Render it with `st.markdown` (raw
HTML off, the default); anything else that needs the words calls `plain_text`.

Code is found with this module's own simple rules, not a full markdown parser:
- a code block starts at a line whose first characters (after at most 3 spaces) are 3 or more
  backticks or tildes, and ends at the next line holding only the same character, at least as
  many times, or at the end of the text;
- inline code is a run of backticks not preceded by a backslash, up to the next run of exactly
  as many backticks on the same line;
- everything else is text.
When a renderer would have read the model's text differently, the difference only decides
whether a piece shows as code or as text. It can't make anything live, because only the output
of `to_markdown` is ever rendered, and in it text holds no backtick at all.

Citation markers: a bracket pair (ASCII, escaped, full-width, lenticular, tortoise-shell,
white or vertical-form) is a citation if what it holds is whole numbers or ranges, separated
by commas, semicolons, "and" or spaces, optionally after a word for "source" in one of several
languages ([Source 2], [Quelle 2], [来源 2], [S2]) or ^ or #, or before a †word tail
([1†source]). Digits may be full-width, superscript, circled or CJK numerals, and zero-width
characters are ignored. Anything else in brackets is text and shown as written: [3.14],
[10:30], [1.2.3], [2^3], [Q4], [A1], a phone number. Bracketed whole numbers that weren't
meant as citations are still read as citations and checked, because they look exactly like
one: [2023], [3, 4], [1 2 3], [2 ^3], [2,3] (a decimal comma), "chapter [2], verse [3]", [S2] (S is
a word for source). They are removed when they name no sent source and cited when they do;
the model is told to write citations only.
"""

import re
import string
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Segment:
    kind: Literal["text", "inline_code", "code_block"]
    text: str  # for code, the code itself, without its delimiters
    info: str = ""  # a code block's language, e.g. "python"


@dataclass(frozen=True)
class Cite:
    """A checked citation marker, shown as [number]."""

    number: int


Piece = Segment | Cite


class TooNested(ValueError):
    """Removing markers kept forming new ones for more than MAX_PASSES rounds."""


MAX_PASSES = 5
WORD_JOINER = "\u2060"
_LINE_BREAKS = "\r\x0b\x0c\x85\u2028\u2029"
_KEPT_FORMAT_CHARACTERS = {"\u200c", "\u200d"}  # ZWNJ, ZWJ: needed by Persian, Hindi, emoji
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
_BACKTICKS = re.compile(r"`+")
_INFO = re.compile(r"[A-Za-z0-9_+.#-]{1,30}")  # a code block language worth keeping
_PUNCTUATION = frozenset(string.punctuation)
_SPACES = re.compile(r"[ \t]+")

_OPEN = "[［【〖〔⟦﹇﹝⁅〘"
_CLOSE = "]］】〗〕⟧﹈﹞⁆〙"
_BRACKETS = "".join(re.escape(c) for c in _OPEN + _CLOSE)
# A marker candidate: one bracket pair around at most 100 characters on one line (spaces are
# collapsed first), or around a number of any length. Bounded, so matching stays linear.
MARKER = re.compile(
    rf"\\?[{''.join(re.escape(c) for c in _OPEN)}]"
    rf"(?P<inner>[^{_BRACKETS}\n]{{0,100}}|\ ?\d+\ ?\\?)"
    rf"[{''.join(re.escape(c) for c in _CLOSE)}]"
)
# Words for "source" a citation may start with, in the languages the model may answer in.
_SOURCE_WORDS = frozenset(
    "s src source sources doc docs document documents ref refs reference references cite "
    "citation citations see quelle quellen fuente fuentes fonte fontes bron bronnen kilde "
    "källa źródło kaynak sumber nguồn источник источники مصدر מקור स्रोत 来源 出处 出處 出典 "
    "参考 參考 文献 출처".split()
)
_CJK_DIGITS = str.maketrans("〇零一二三四五六七八九", "00123456789")
# Tokens a citation is made of (see `citation_items`).
_TOKEN = re.compile(r"[^\W\d_]+|\d+|[-–—−~〜]+|\s+|\S")
_DASH = re.compile(r"[-–—−~〜]+")
_LIST_SEPARATORS = frozenset(",;&、，；") | {"and", "or", "und", "et", "y"}
_RANGE_WORDS = frozenset({"to", "bis"})
_LEADING = frozenset("^#†\\")  # [^1] [#1] [†1] and [\\1] (from an escaped bracket)
_DATA = re.compile(r"\d+(?:-\d+){2,}")  # 1-800-555-1234, 2026-11-27: data, not a range
_PLACEHOLDER = re.compile("\x00(\\d+)\x01")  # a checked marker, between passes
_CODE_START, _CODE_END = "\x02", "\x03"  # inline code, in drop_citations_across_code
_INDEXED = re.compile(r"[\w)\]]\x03")  # code ending in a name or a bracket, right here


def hidden(char: str) -> bool:
    """Whether `char` is invisible or a control character with no place in an answer: format
    characters (zero-width, bidi controls, tag characters) other than ZWNJ and ZWJ, private-use
    characters, lone surrogates, and control characters other than tab and newline."""
    category = unicodedata.category(char)
    if category == "Cf":
        return char not in _KEPT_FORMAT_CHARACTERS
    return category in {"Cc", "Co", "Cs"} and char not in "\n\t"


def clean(text: str) -> str:
    """`text` with every line break as "\\n" and no `hidden` characters. (Tag-based emoji
    flags lose their tags; tags are also how invisible instructions are smuggled.)"""
    text = text.replace("\r\n", "\n")
    return "".join(
        "\n" if c in _LINE_BREAKS else c for c in text if not hidden(c) or c in _LINE_BREAKS
    )


def _spaced_items(tokens: list[str]) -> list[str]:
    """Tokens without spaces, except that a space next to an item's decoration separates items
    ([^7 ^8], [1† 2†], [1†source 2†source], and so [2 ^3] too, like [1 2])."""
    result: list[str] = []
    for i, token in enumerate(tokens):
        if not token.isspace():
            result.append(token)
            continue
        after = tokens[i + 1] if i + 1 < len(tokens) else ""
        before = result[-1] if result else ""
        trailing = before in ("\\", "†") or (
            len(result) >= 2 and result[-2] == "†" and before in _SOURCE_WORDS
        )
        if result and after and (after in _LEADING or trailing):
            result.append(",")
    return result


def _undecorated(tokens: list[str]) -> list[str]:
    """One item's tokens without leading ^ # † \\ and trailing \\ † †source (repeated)."""
    while tokens and tokens[0] in _LEADING:
        tokens = tokens[1:]
    while tokens:
        if tokens[-1] in ("\\", "†"):
            tokens = tokens[:-1]
        elif len(tokens) >= 2 and tokens[-2] == "†" and tokens[-1] in _SOURCE_WORDS:
            tokens = tokens[:-2]
        else:
            break
    return tokens


def citation_items(inner: str) -> list[str] | None:
    """The items of a marker's inside ("1", "2-4", and malformed ones such as "-1" or "3-" for
    the caller to refuse) if it reads as a citation, else None.

    It reads as one if, after at most one leading word for "source" (with "." or ":") and the
    decorations ^ # † \\ at the start, and before a "\\" or a †word at the end, it holds a number
    and nothing but numbers, list separators (, ; & 、 and or ...), dashes and "to". Digits may
    be any script's, superscript, circled or CJK numerals; format characters are ignored."""
    text = "".join(c for c in inner if unicodedata.category(c) != "Cf")
    text = unicodedata.normalize("NFKC", text).translate(_CJK_DIGITS)
    text = "".join(
        str(unicodedata.digit(c))
        if not c.isascii() and unicodedata.digit(c, None) is not None
        else c
        for c in text
    )
    tokens = _spaced_items(_TOKEN.findall(text.lower()))
    if tokens and tokens[0] in _SOURCE_WORDS:
        tokens = tokens[1 + (tokens[1:2] in ([":"], ["."])) :]
    # Decorations go at the edges of each item ([^1, ^2], [1†source, 2†source]); anywhere else
    # ([2^3], [1#2], [1†2]) they leave a token that fails below, so the bracket is text.
    groups: list[list[str]] = [[]]
    for token in tokens:
        if token in _LIST_SEPARATORS:
            groups.append([token])
            groups.append([])
        else:
            groups[-1].append(token)
    tokens = [t for group in groups for t in _undecorated(group)]
    if not any(t.isdigit() for t in tokens) or any(
        not (t.isdigit() or _DASH.fullmatch(t) or t in _LIST_SEPARATORS or t in _RANGE_WORDS)
        for t in tokens
    ):
        return None
    items, item = [], ""
    for token in tokens:
        if token in _LIST_SEPARATORS:
            items.append(item)
            item = ""
        elif token.isdigit():
            if item[-1:].isdigit():  # "1 2": two items
                items.append(item)
                item = ""
            item += token
        else:
            item += "-"  # a dash or "to": a range, or a malformed item ("-1", "3-")
    items.append(item)
    items = [i for i in items if i]
    if any(_DATA.fullmatch(i) for i in items):
        return None
    return items


def rewrite_citations(text: str, resolve: Callable[[list[str]], list[int]]) -> list[Piece]:
    """One text segment as pieces, every citation marker replaced by `Cite(n)` for each number
    `resolve(items)` returns (none: the marker goes, with the space before it).

    Spaces are collapsed first. Removing a marker can join the text around it into a new one
    ("[[9]7]" -> "[7]"), and a marker can sit inside another ("[7[1]]"), so this repeats until
    nothing changes, at most MAX_PASSES times (then TooNested). Markers already checked wait
    as placeholders (clean() removed every real \\x00 and \\x01), so they are never counted
    twice; a bracket around them is dropped."""
    work = _SPACES.sub(" ", text)
    for _ in range(MAX_PASSES):
        work, found = _rewrite_once(work, resolve)
        if not found:
            break
    else:
        raise TooNested("citation markers nested too deeply")
    return [
        Cite(int(part)) if i % 2 else Segment("text", part)
        for i, part in enumerate(_PLACEHOLDER.split(work))
    ]


def _rewrite_once(
    text: str, resolve: Callable[[list[str]], list[int]], across_code: bool = False
) -> tuple[str, bool]:
    """One pass of `rewrite_citations`. With `across_code`, `text` is a line with its inline
    code between \\x02 and \\x03, and only markers that include part of the code are touched."""
    out: list[str] = []
    pos, found = 0, False
    for match in MARKER.finditer(text):
        inner = match.group("inner")
        if across_code and (
            not set(match.group()) & {_CODE_START, _CODE_END}
            or _INDEXED.fullmatch(text, max(0, match.start() - 2), match.start())  # an index
        ):
            continue
        checked = _PLACEHOLDER.findall(inner)
        rest = _PLACEHOLDER.sub(" ", inner).replace(_CODE_START, "").replace(_CODE_END, "")
        items = citation_items(rest)
        if items is not None:
            numbers = checked + [str(n) for n in resolve(items)]
        elif checked and all(c.isspace() or unicodedata.category(c)[0] in "PS" for c in rest):
            numbers = checked  # brackets around checked markers only
        else:
            continue  # not a citation: shown as text
        found = True
        before = text[pos : match.start()]
        new = "".join(f"\x00{n}\x01" for n in numbers[len(checked) :])
        if across_code:
            kept = inner.removesuffix("\\")  # only the brackets go: "[`7`]" -> "`7`"
        else:
            kept = "".join(f"\x00{n}\x01" for n in checked) + new
        out.append(before if kept else before.rstrip(" "))  # a marker that leaves nothing
        out.append(kept)
        pos = match.end()
    out.append(text[pos:])
    return "".join(out), found


def drop_citations_across_code(pieces: list[Piece]) -> list[Piece]:
    """`pieces` without the brackets of any bracket pair that reads as a citation only together
    with the inline code inside it ("[`7`]" shows as [7]; it becomes "`7`"). Markers in text were
    already checked by `rewrite_citations`; brackets wholly inside code, or right after code
    that ends in a name or a bracket (`items`[`0`], `f()`[`0`], an index), are left alone. The
    price: `Paid`[`7`] also reads as an index and shows as written."""
    result: list[Piece] = []
    run: list[Piece] = []  # inline pieces between code blocks

    def flush() -> None:
        if any(isinstance(p, Segment) and p.kind == "inline_code" for p in run):
            line = "".join(
                f"\x00{p.number}\x01"
                if isinstance(p, Cite)
                else f"{_CODE_START}{p.text}{_CODE_END}"
                if p.kind == "inline_code"
                else p.text
                for p in run
            )
            for _ in range(MAX_PASSES):
                line, found = _rewrite_once(line, lambda items: [], across_code=True)
                if not found:
                    break
            else:
                raise TooNested("citation markers nested too deeply")
            result.extend(_pieces_of_line(line))
        else:
            result.extend(run)
        run.clear()

    for piece in pieces:
        if isinstance(piece, Segment) and piece.kind == "code_block":
            flush()
            result.append(piece)
        else:
            run.append(piece)
    flush()
    return result


_LINE_PART = re.compile(f"\x00(\\d+)\x01|{_CODE_START}([^{_CODE_END}]*)(?:{_CODE_END}|$)")


def _pieces_of_line(line: str) -> list[Piece]:
    """The inverse of the line `drop_citations_across_code` builds. A code part that lost its
    start or end to a removed marker is kept as code (start) or dropped (stray end)."""
    pieces: list[Piece] = []
    pos = 0
    for match in _LINE_PART.finditer(line):
        pieces.append(Segment("text", line[pos : match.start()].replace(_CODE_END, "")))
        if match.group(1) is not None:
            pieces.append(Cite(int(match.group(1))))
        else:
            pieces.append(Segment("inline_code", match.group(2)))
        pos = match.end()
    pieces.append(Segment("text", line[pos:].replace(_CODE_END, "")))
    return [p for p in pieces if not (isinstance(p, Segment) and not p.text)]  # empty parts go


def segments(text: str) -> list[Segment]:
    """`text` split into text, inline code and code blocks by the rules above."""
    result: list[Segment] = []
    lines = text.split("\n")
    buffer: list[str] = []
    i = 0
    while i < len(lines):
        opening = _FENCE.fullmatch(lines[i])
        if opening is None or (opening.group(1)[0] == "`" and "`" in opening.group(2)):
            buffer.append(lines[i])
            i += 1
            continue
        fence = opening.group(1)
        closing = re.compile(rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*")
        body = []
        i += 1
        while i < len(lines) and not closing.fullmatch(lines[i]):
            body.append(lines[i])
            i += 1
        i += 1  # past the closing line
        if buffer:
            result += _inline("\n".join(buffer))
            buffer = []
        info = opening.group(2).strip()
        result.append(Segment("code_block", "\n".join(body), info if _INFO.fullmatch(info) else ""))
    if buffer:
        result += _inline("\n".join(buffer))
    return result


def _inline(text: str) -> list[Segment]:
    """Text with its inline code split out. Linear: each backtick run is visited once."""
    runs = [m.span() for m in _BACKTICKS.finditer(text)]
    line_of, line, counted = [], 0, 0
    for start, _ in runs:
        line += text.count("\n", counted, start)
        counted = start
        line_of.append(line)
    # next_same[r]: the next run on the same line with the same length, if any.
    next_same: list[int | None] = [None] * len(runs)
    seen: dict[tuple[int, int], int] = {}
    for r in range(len(runs) - 1, -1, -1):
        key = (line_of[r], runs[r][1] - runs[r][0])
        next_same[r] = seen.get(key)
        seen[key] = r
    result: list[Segment] = []
    pos = 0
    r = 0
    while r < len(runs):
        start, end = runs[r]
        if start < pos or _escaped(text, start) or next_same[r] is None:
            r += 1
            continue
        close = next_same[r]
        if start > pos:
            result.append(Segment("text", text[pos:start]))
        result.append(Segment("inline_code", text[end : runs[close][0]]))
        pos = runs[close][1]
        r = close + 1
    if pos < len(text):
        result.append(Segment("text", text[pos:]))
    return result


def _escaped(text: str, index: int) -> bool:
    """Whether the character at `index` follows an odd number of backslashes."""
    count = 0
    while index - count > 0 and text[index - count - 1] == "\\":
        count += 1
    return count % 2 == 1


def _tidy(pieces: Iterable[Piece]) -> list[Piece]:
    """Pieces without empty text, with text next to text merged (escaped as one, so no arrow
    or link forms across the seam) and inline code next to inline code merged (written side by
    side, their backticks would touch and read as one longer run)."""
    tidy: list[Piece] = []
    for piece in pieces:
        if isinstance(piece, Segment) and piece.kind == "text" and not piece.text:
            continue
        last = tidy[-1] if tidy else None
        if (
            isinstance(piece, Segment)
            and piece.kind == "text"
            and isinstance(last, Segment)
            and last.kind == "text"
        ):
            tidy[-1] = Segment("text", last.text + piece.text)
            continue
        if (
            isinstance(piece, Segment)
            and piece.kind == "inline_code"
            and isinstance(last, Segment)
            and last.kind == "inline_code"
        ):
            tidy[-1] = Segment("inline_code", last.text + piece.text)
        else:
            tidy.append(piece)
    return tidy


_ARROW = frozenset("<->=~")


_CODE_NAME = re.compile(r"[\w+-]*:")  # what may follow ":" up to the ":" ending a :code:


def _joiner_at(text: str, i: int) -> bool:
    """Whether a word joiner goes between text[i - 1] and text[i] (see the module docstring)."""
    before, char = text[i - 1], text[i]
    if before == ":" and (char in "/+-_" or char.isalnum()):
        # 10:30 and 1:2 need none, unless what follows could end in ":" (10:30:45 -> ":30:").
        time_like = char.isdigit() and i >= 2 and text[i - 2].isdigit()
        return not time_like or bool(_CODE_NAME.match(text, i))
    return (
        "@" in (before, char)
        or (char == "." and text[max(0, i - 3) : i].lower() == "www")
        or (before in _ARROW and char in _ARROW)
    )


def _escape(text: str) -> str:
    """Text as markdown that shows exactly it (see the module docstring). Newlines become
    \\x00 for `to_markdown` to place."""
    text = _SPACES.sub(" ", text)
    out: list[str] = []
    for i, char in enumerate(text):
        if i and _joiner_at(text, i):
            out.append(WORD_JOINER)
        if char in _PUNCTUATION:
            out.append("&#96;" if char == "`" else "\\" + char)
        elif char == "\n":
            out.append("\x00")
        else:
            out.append(char)
    return "".join(out)


def to_markdown(pieces: Iterable[Piece]) -> str:
    """Pieces as markdown that renders exactly as the text, the code and the checked markers."""
    out: list[str] = []
    line: list[str] = []  # the current run of inline pieces, between code blocks

    def finish_line() -> None:
        joined = "".join(line).strip("\x00 ")
        # \x00 marks a newline of the text (clean() removed every real \x00). Two or more in a
        # row end a paragraph; one is a line break. A space around them would start the next
        # line indented, so it goes. Spaces are already single, so this stays linear.
        joined = re.sub(" ?\x00(?: ?\x00)+ ?", "\n\n", joined)
        joined = re.sub(" ?\x00 ?", "\\\\\n", joined)
        if joined:
            out.append(joined)
        line.clear()

    for piece in _tidy(pieces):
        if isinstance(piece, Cite):
            line.append(f"[{piece.number}]")
        elif piece.kind == "text":
            line.append(_escape(piece.text))
        elif piece.kind == "inline_code":
            line.append(_inline_code(piece.text))
        else:
            finish_line()
            fence = "`" * max(3, _longest_run(piece.text) + 1)
            out.append(
                f"{fence}{piece.info}\n{piece.text}\n{fence}"
                if piece.text
                else f"{fence}{piece.info}\n{fence}"
            )
    finish_line()
    return "\n\n".join(out)


def _inline_code(code: str) -> str:
    ticks = "`" * (_longest_run(code) + 1)
    if code.strip() and (code[0] in " `" or code[-1] in " `"):
        code = f" {code} "  # a renderer strips one space from each end
    return f"{ticks}{code}{ticks}"


def _longest_run(code: str) -> int:
    return max((len(m.group()) for m in _BACKTICKS.finditer(code)), default=0)


# In to_markdown's text: an escaped character, a line break, or a marker (with its space).
_OUR_TEXT = re.compile(r"\\([!-/:-@\[-`{-~])|(\\\n)|( ?\[\d+\])")


def plain_text(markdown: str, citations: bool = True) -> str:
    """Markdown made by `to_markdown` back as plain text: escapes, word joiners and line-break
    marks removed, code kept, and the [n] markers too unless `citations` is False."""
    parts = segments(markdown)
    pieces: list[Piece] = []
    for i, segment in enumerate(parts):
        if segment.kind == "text":
            text = segment.text
            if i > 0 and parts[i - 1].kind == "code_block":
                text = text.removeprefix("\n")  # the blank line after a block
            if i + 1 < len(parts) and parts[i + 1].kind == "code_block":
                text = text.removesuffix("\n")  # the blank line before one
            # Our own backticks first (a literal "&#96;" in the text was escaped, so it can't
            # match), then joiners, markers, line breaks and escapes.
            text = text.replace("&#96;", "\x02").replace(WORD_JOINER, "")
            # One left-to-right pass, so an escaped backslash before a line break or a marker
            # is read correctly. Every other bracket is escaped, so a bare "[n]" is our marker.
            text = _OUR_TEXT.sub(
                lambda m: m.group(1) or ("\n" if m.group(2) else m.group(3) if citations else ""),
                text,
            )
            segment = Segment("text", text.replace("\x02", "`"))
        pieces.append(segment)
    return to_plain(pieces)


def to_plain(pieces: Iterable[Piece]) -> str:
    """Pieces as plain text: text as it is, markers as [n], code with its delimiters."""
    out = []
    for piece in _tidy(pieces):
        if isinstance(piece, Cite):
            out.append(f"[{piece.number}]")
        elif piece.kind == "text":
            out.append(piece.text)
        elif piece.kind == "inline_code":
            out.append(_inline_code(piece.text))
        else:
            fence = "`" * max(3, _longest_run(piece.text) + 1)
            before = "" if not out or out[-1].endswith("\n") else "\n"
            out.append(f"{before}{fence}{piece.info}\n{piece.text}\n{fence}\n")
    return "".join(out).strip("\n")


def strip_citations(text: str) -> str:
    """`text` (plain) without its citation markers, and the spaces before them; code kept."""
    pieces: list[Piece] = []
    for segment in segments(clean(text)):
        if segment.kind != "text":
            pieces.append(segment)
            continue
        try:
            pieces += rewrite_citations(segment.text, lambda items: [])
        except TooNested:
            pieces.append(Segment("text", re.sub(f"[{_BRACKETS}]", "", segment.text)))
    return to_plain(pieces)
