from __future__ import annotations

from cli.dataset import main as dataset_main


def main(argv: list[str] | None = None) -> int:
    return dataset_main(argv)
