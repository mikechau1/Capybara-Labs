"""Shared ingestion pipeline. Card M2-04 owns this file."""


def run_ingest(source_name: str) -> None:
    # TODO(M2-04): look up the source registration, run its connector from the stored cursor,
    # chunk, embed (app.shared.embeddings), upsert by source + external ID + content hash,
    # remove items the connector no longer reports, then store the new cursor.
    raise NotImplementedError("Card M2-04")


def run_all() -> None:
    raise NotImplementedError("Card M2-04")
