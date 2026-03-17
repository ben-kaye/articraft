from __future__ import annotations

from dataclasses import dataclass

from store.models import CategoryRecord
from store.repo import StoreRepo


@dataclass(slots=True)
class CategoryStore:
    repo: StoreRepo

    def save(self, category: CategoryRecord) -> None:
        path = self.repo.layout.category_metadata_path(category.slug)
        self.repo.write_json(path, category.to_dict())

    def load(self, category_slug: str) -> dict | None:
        return self.repo.read_json(self.repo.layout.category_metadata_path(category_slug))
