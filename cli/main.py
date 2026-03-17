from __future__ import annotations

import argparse

from cli import dataset as dataset_cli
from cli import workbench as workbench_cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="articraft")
    subparsers = parser.add_subparsers(dest="surface", required=True)
    subparsers.add_parser("dataset")
    subparsers.add_parser("workbench")
    args, remainder = parser.parse_known_args(argv)

    if args.surface == "dataset":
        return dataset_cli.main(remainder)
    if args.surface == "workbench":
        return workbench_cli.main(remainder)

    parser.error(f"Unhandled surface: {args.surface}")
    return 2
