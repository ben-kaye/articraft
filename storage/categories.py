"""Category metadata: a slug + title + description. One JSON file per category."""

from __future__ import annotations

from .repo import Repo


class CategoryStore:
    def __init__(self, repo: Repo):
        self.repo = repo
        self.layout = repo.layout

    def save(self, slug: str, title: str = "", description: str = "") -> dict:
        data = {"slug": slug, "title": title or slug, "description": description}
        self.repo.write_json(self.layout.category_json(slug), data)
        return data

    def load(self, slug: str) -> dict:
        return self.repo.read_json(self.layout.category_json(slug))

    def list(self) -> list[str]:
        d = self.layout.categories_dir
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.json"))

    def delete(self, slug: str) -> None:
        self.layout.category_json(slug).unlink(missing_ok=True)
