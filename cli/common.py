from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

from storage.datasets import DatasetStore
from storage.repo import StorageRepo
from storage.revisions import active_provenance_path


def add_data_root_argument(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root containing the data/ directory.",
    )


def provider_for_record_image(
    repo: StorageRepo,
    record_id: str,
    *,
    provider_override: str | None = None,
) -> str:
    if provider_override:
        return provider_override

    record = repo.read_json(repo.layout.record_metadata_path(record_id), default={}) or {}
    if isinstance(record, dict):
        record_provider = record.get("provider")
        if isinstance(record_provider, str) and record_provider.strip():
            return record_provider

    provenance = repo.read_json(active_provenance_path(repo, record_id), default={}) or {}
    generation = provenance.get("generation") if isinstance(provenance, dict) else {}
    provider = generation.get("provider") if isinstance(generation, dict) else None
    if isinstance(provider, str) and provider.strip():
        return provider
    return "openai"


def refresh_dataset_manifest_if_member(repo: StorageRepo, record_id: str) -> bool:
    datasets = DatasetStore(repo)
    if datasets.load_entry(record_id) is None:
        return False
    datasets.write_dataset_manifest()
    return True
