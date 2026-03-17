from __future__ import annotations

from cli.workbench import main as workbench_main


def main(argv: list[str] | None = None) -> int:
    return workbench_main(argv)
