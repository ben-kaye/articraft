from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path


def add_data_root_argument(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root containing the data/ directory.",
    )
