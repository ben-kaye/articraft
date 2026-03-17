from __future__ import annotations

from dataclasses import dataclass

from store.models import DatasetCollection, WorkbenchCollection
from store.repo import StoreRepo


@dataclass(slots=True)
class CollectionStore:
    repo: StoreRepo

    def save_dataset(self, collection: DatasetCollection) -> None:
        self.repo.write_json(self.repo.layout.dataset_collection_path(), collection.to_dict())

    def save_workbench(self, collection: WorkbenchCollection) -> None:
        self.repo.write_json(self.repo.layout.workbench_collection_path(), collection.to_dict())

    def load_dataset(self) -> dict | None:
        return self.repo.read_json(self.repo.layout.dataset_collection_path())

    def load_workbench(self) -> dict | None:
        return self.repo.read_json(self.repo.layout.workbench_collection_path())
