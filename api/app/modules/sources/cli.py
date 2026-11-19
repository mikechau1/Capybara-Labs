"""Ingestion command. Run with: python -m app.modules.sources.cli --all"""

import argparse

from app.modules.sources import pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest company data sources.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", help="name of one registered source")
    group.add_argument("--all", action="store_true", help="every registered source")
    args = parser.parse_args()

    if args.all:
        pipeline.run_all()
    else:
        pipeline.run_ingest(args.source)


if __name__ == "__main__":
    main()
