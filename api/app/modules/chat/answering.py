"""The answer step: retrieved chunks in, an answer whose every citation is real out.
Card M3-04 owns this file. The pipeline (card M3-05) calls `answer_from_chunks`.

    checked = answer_from_chunks(llm, question, chunks, history, deadline=deadline)
    checked.text     # markdown, safe to render: ChatResponse.answer; also what M3-06 stores
    checked.sources  # chat.schemas.Source items, numbered 1, 2, ... to match the [n] in text
    checked.cited    # the RetrievedChunk behind each source, in the same order
    checked.status   # "answered", or "nothing_found" when there were no chunks

`cited` is meant for the audit event's chunks_cited (the chunks passed in are
chunks_retrieved), but M3-07's ChunkRef needs a document id, which RetrievedChunk doesn't carry
yet (card M2-07 adds it).

Rules it enforces:
- No chunks: the fixed NOTHING_FOUND text is returned and the model is not called at all.
- The model's reply is never shown as it came: `app/shared/answer_text.py` rebuilds it, so
  the markdown it returns shows the model's text literally (no link, image, HTML or formatting
  can form) apart from code, which stays code, and the citation markers checked here.
- The [n] markers in the answer text are the citations. `DraftAnswer.cited` (the model's own
  list) is ignored: only what the user would see counts. Markers are read in the forms models
  write (see `app/shared/answer_text.py`): [1], [ 2 ], [1, 3], [2-4], [1 and 3], [^5],
  [Source 6], [Quelle 6], [S6], escaped \\[7\\], full-width ［8］, superscript [⁹],
  【1†source】, with zero-width characters ignored. Other bracketed text is shown as written,
  so a number in a form not listed there ([7, p. 3], (7)) is shown too; the rules tell the
  model to cite as [n].
- A marker naming any number that wasn't sent (e.g. [7] when 3 chunks were sent, [0], [2023],
  [1, 7], [2-9]) is removed whole, with the spaces before it, and logged with its numbers
  only, never the answer or chunk text.
- The remaining sources are renumbered 1, 2, ... in the order the answer first cites them,
  and each is written as [n] ([1, 3] becomes [1][2]), so the sources list holds exactly the
  cited chunks. The same chunk passed twice would be two sources; retrieval (M2-07) passes each
  chunk once.
- Markers inside code are code, not citations: they are shown as code and never checked.
- An answer that is only citation markers, with no words, is LLMBadOutput.
- Errors from the model are not caught here: LLMUnavailable (after RetryingLLM's retry) and
  LLMBadOutput reach the pipeline, which shows the user an error (card M5-03). An answer that
  is empty, longer than MAX_ANSWER_CHARS, not text, or nothing but removed markers is
  LLMBadOutput too.
- An answer that cites nothing valid is kept, with no sources, and logged (it may honestly
  say "the sources don't cover this"). The pipeline decides how to present it.

What the model is sent, including how chunk text is fenced off as untrusted data, is in
`app/modules/llm/prompts.py`.
"""

import logging
import re
from typing import Literal

from pydantic import BaseModel

from app.modules.chat.schemas import Source
from app.modules.llm.base import LLM, LLMBadOutput, Turn
from app.modules.retrieval.gateway import RetrievedChunk
from app.shared.answer_text import (
    Cite,
    Piece,
    Segment,
    TooNested,
    clean,
    drop_citations_across_code,
    rewrite_citations,
    segments,
    to_markdown,
    to_plain,
)

log = logging.getLogger(__name__)

NOTHING_FOUND = "I couldn't find anything you have access to that answers this question."
SNIPPET_CHARS = 240  # longest snippet shown under a source in the sources panel
MAX_ANSWER_CHARS = 20_000  # far more than any real answer; a longer one is a runaway model
MAX_LOGGED = 20  # invalid markers logged per answer

_NUMBER = re.compile(r"\d{1,6}")
_RANGE = re.compile(r"(\d{1,6})\s*(?:[-–—−~〜]+|to|bis)\s*(\d{1,6})", re.IGNORECASE)


class CheckedAnswer(BaseModel):
    text: str
    sources: list[Source]
    cited: list[RetrievedChunk]
    status: Literal["answered", "nothing_found"]


def answer_from_chunks(
    llm: LLM,
    question: str,
    chunks: list[RetrievedChunk],
    history: list[Turn],
    *,
    deadline: float | None = None,
) -> CheckedAnswer:
    """The model's answer to `question` from `chunks` only, with its citations checked."""
    if not chunks:
        text = to_markdown([Segment("text", NOTHING_FOUND)])
        return CheckedAnswer(text=text, sources=[], cited=[], status="nothing_found")

    draft = llm.answer(question, chunks, history, deadline=deadline)
    raw = getattr(draft, "text", None)
    if not isinstance(raw, str):
        raise LLMBadOutput("the model's answer was not in the expected shape")
    if len(raw) > MAX_ANSWER_CHARS:
        raise LLMBadOutput("the model's answer was too long")

    pieces, order, invalid = check_citations(clean(raw), len(chunks))
    if not to_plain(p for p in pieces if not isinstance(p, Cite)).strip():
        raise LLMBadOutput("the model's answer was empty")
    if invalid:
        log.warning(
            "removed citations of sources that were not sent",
            extra={"invalid_citations": invalid[:MAX_LOGGED], "sources_sent": len(chunks)},
        )
    cited = [chunks[number - 1] for number in order]
    if not cited:
        log.warning("the answer cites no source", extra={"sources_sent": len(chunks)})
    sources = [
        Source(
            number=number,
            title=chunk.document_title,
            department=chunk.department,
            source_type=chunk.source_type,
            link=chunk.link,
            snippet=snippet(chunk.text),
        )
        for number, chunk in enumerate(cited, start=1)
    ]
    return CheckedAnswer(text=to_markdown(pieces), sources=sources, cited=cited, status="answered")


def check_citations(text: str, sent: int) -> tuple[list[Piece], list[int], list[str]]:
    """The cleaned answer `text` as pieces, with every citation marker outside code checked
    against `sent` numbered sources (1..sent) and renumbered.

    Returns the pieces, the original numbers of the valid sources in order of first citation
    (its position + 1 is each one's new number), and the invalid items found.
    """
    order: list[int] = []
    new_number: dict[int, int] = {}
    invalid: list[str] = []

    def resolve(items: list[str]) -> list[int]:
        # All or nothing: a marker naming any source that wasn't sent goes whole, so a made-up
        # number can never leave a real citation behind ([3, 4] in "[x, y] = [3, 4]").
        found = [(item, _numbers(item, sent)) for item in items]
        bad = [item for item, numbers in found if numbers is None]
        if bad:
            invalid.extend(bad)
            return []
        cites: list[int] = []
        for _, numbers in found:
            for number in numbers:
                if number not in new_number:
                    order.append(number)
                    new_number[number] = len(order)
                if new_number[number] not in cites:
                    cites.append(new_number[number])
        return cites

    pieces: list[Piece] = []
    for segment in segments(text):
        if segment.kind != "text":
            pieces.append(segment)
            continue
        try:
            pieces += rewrite_citations(segment.text, resolve)
        except TooNested:
            raise LLMBadOutput("the model's answer had too many nested citations") from None
    try:
        pieces = drop_citations_across_code(pieces)  # "[`7`]" reads as [7] too
    except TooNested:
        raise LLMBadOutput("the model's answer had too many nested citations") from None
    return pieces, order, invalid


def _numbers(item: str, sent: int) -> list[int] | None:
    """The source numbers one item of a marker names ("3", or a range "2-4"), or None if any
    of them wasn't sent or the item isn't a number or range of at most 6 digits each."""
    if _NUMBER.fullmatch(item):
        first = last = int(item)
    elif match := _RANGE.fullmatch(item):
        first, last = int(match.group(1)), int(match.group(2))
    else:
        return None
    if not 1 <= first <= last <= sent:
        return None
    return list(range(first, last + 1))


def snippet(text: str) -> str:
    """The start of a chunk's text for the sources panel, cut at a word boundary."""
    flat = " ".join(text.split())
    if len(flat) <= SNIPPET_CHARS:
        return flat
    cut = flat[: SNIPPET_CHARS - 1]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut + "…"
