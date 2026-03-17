from __future__ import annotations

from dataclasses import dataclass

from store.collections import CollectionStore
from store.repo import StoreRepo


@dataclass(slots=True)
class ManifestStore:
    repo: StoreRepo
    collections: CollectionStore

    def dataset_manifest(self) -> dict:
        collection = self.collections.load_dataset() or {"entries": []}
        generated = [
            {
                "name": entry["dataset_id"],
                "record_id": entry["record_id"],
            }
            for entry in collection.get("entries", [])
        ]
        return {"generated": generated}
