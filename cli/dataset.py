from __future__ import annotations

import argparse
from datetime import datetime, timezone

from store.collections import CollectionStore
from store.models import DatasetCollection
from store.queries import StoreQueries
from store.repo import StoreRepo

from cli.common import add_data_root_argument


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="articraft-dataset")
    add_data_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-store", help="Create the canonical data/ directory layout.")
    subparsers.add_parser("status", help="Show dataset storage status.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    repo = StoreRepo(args.repo_root)
    collections = CollectionStore(repo)
    queries = StoreQueries(repo)

    if args.command == "init-store":
        repo.ensure_layout()
        if collections.load_dataset() is None:
            collections.save_dataset(
                DatasetCollection(
                    schema_version=1,
                    collection="dataset",
                    updated_at=_utc_now(),
                )
            )
        print(f"Initialized dataset store at {repo.layout.data_root}")
        return 0

    if args.command == "status":
        record_count = len(queries.list_record_ids())
        category_count = len(queries.list_category_slugs())
        dataset_entries = (collections.load_dataset() or {}).get("entries", [])
        print(f"records={record_count} categories={category_count} dataset_entries={len(dataset_entries)}")
        return 0

    parser.error(f"Unhandled command: {args.command}")
    return 2
