"""sources: getting company data in.

- connectors/   one file per source type; each yields normalized SourceItems
    docs.py       card M2-05
    tickets.py    card M4-07
    discord.py    card M4-09
- pipeline.py   chunk, embed, upsert, tombstone (card M2-04)
- cli.py        `python -m app.modules.sources.cli --all` (card M2-04, scheduled by M4-10)
- router.py     sources list and "Sync now" (card M4-10)
- models.py     tables: departments, sources, documents, chunks

Department always comes from the source registration, never from content. Unknown sensitivity
means restricted. Only the retrieval module reads chunks; this module only writes them.
"""
