"""Promote a workbench record into the dataset. Promotion is just a state flip on the record."""

from __future__ import annotations

from .records import RecordStore, now_iso
from .repo import Repo


class DatasetStore:
    def __init__(self, repo: Repo):
        self.repo = repo
        self.layout = repo.layout
        self.records = RecordStore(repo)

    def promote(self, record_id: str, dataset_id: str, category_slug: str | None = None) -> None:
        record = self.records.load(record_id)
        collections = [c for c in record.collections if c != "workbench"]
        if "dataset" not in collections:
            collections.append("dataset")
        update = {
            "collections": collections,
            "dataset_id": dataset_id,
            "updated_at": now_iso(),
        }
        if category_slug is not None:
            update["category_slug"] = category_slug
        record = record.model_copy(update=update)
        self.repo.write_json(self.layout.record_json(record_id), record.model_dump())

    def members(self) -> list[str]:
        return [
            rid
            for rid in self.records.list_ids()
            if "dataset" in self.records.load(rid).collections
        ]
