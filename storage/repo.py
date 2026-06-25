"""Repo = root + layout + tiny JSON helpers. Pydantic does the schema work."""

from __future__ import annotations

import json
from pathlib import Path

from .layout import Layout


class Repo:
    def __init__(self, root: Path | str):
        self.layout = Layout(root)

    @property
    def root(self) -> Path:
        return self.layout.root

    @staticmethod
    def read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def write_json(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
