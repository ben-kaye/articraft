from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cli.common import add_data_root_argument
from storage.categories import CategoryStore
from storage.collections import CollectionStore
from storage.datasets import DatasetStore
from storage.models import CategoryRecord
from storage.queries import StorageQueries
from storage.records import RecordStore
from storage.repo import StorageRepo
from storage.search import SearchIndex


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(slots=True, frozen=True)
class DeleteCategoryPreview:
    category_slug: str
    category_title: str
    record_ids: list[str]
    cached_run_ids: list[str]


@dataclass(slots=True, frozen=True)
class DeleteRecordPreview:
    record_id: str
    record_dir: Path
    title: str
    category_slug: str
    run_id: str
    dataset_id: str
    in_workbench: bool


@dataclass(slots=True, frozen=True)
class PruneCachePreview:
    failed_staging_dirs: list[Path]
    empty_dirs: list[Path]


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _build_delete_category_preview(
    repo: StorageRepo, queries: StorageQueries, category_slug: str
) -> DeleteCategoryPreview | None:
    category = CategoryStore(repo).load(category_slug)
    if not isinstance(category, dict):
        return None
    return DeleteCategoryPreview(
        category_slug=category_slug,
        category_title=str(category.get("title") or ""),
        record_ids=queries.list_record_ids_for_category(category_slug),
        cached_run_ids=queries.list_run_ids_for_category(category_slug),
    )


def _print_delete_category_preview(preview: DeleteCategoryPreview) -> None:
    print("Delete category preview")
    print(f"category_slug={preview.category_slug}")
    print(f"category_title={preview.category_title or '(untitled)'}")
    print(f"category_dir={preview.category_slug}")
    print(f"records_to_delete={len(preview.record_ids)}")
    if preview.record_ids:
        print(f"sample_record_ids={', '.join(preview.record_ids[:5])}")
    else:
        print("sample_record_ids=(none)")
    print(f"run_cache_entries_retained={len(preview.cached_run_ids)}")
    if preview.cached_run_ids:
        print(f"sample_run_ids={', '.join(preview.cached_run_ids[:5])}")


def _resolve_record_path(repo: StorageRepo, record_path: str) -> Path:
    resolved = Path(record_path).expanduser().resolve()
    records_root = repo.layout.records_root.resolve()
    try:
        relative = resolved.relative_to(records_root)
    except ValueError as exc:
        raise ValueError(f"Record path must be inside {records_root}") from exc
    if len(relative.parts) != 1:
        raise ValueError(f"Record path must point to a direct child of {records_root}")
    if not resolved.is_dir():
        raise ValueError(f"Record directory not found: {resolved}")
    return resolved


def _resolve_record_reference(repo: StorageRepo, record_ref: str) -> str:
    candidate = Path(record_ref).expanduser()
    if candidate.exists():
        return _resolve_record_path(repo, str(candidate)).name

    record_id = record_ref.strip()
    if not record_id:
        raise ValueError("Record reference is required.")
    if repo.layout.record_dir(record_id).is_dir():
        return record_id
    raise ValueError(f"Record not found: {record_ref}")


def _slugify_category_title(title: str) -> str:
    slug = _NON_ALNUM_RE.sub("_", title.strip().lower()).strip("_")
    if not slug:
        raise ValueError(f"Could not derive category slug from {title!r}")
    return slug


def _sdk_package_to_target_sdk_version(sdk_package: str) -> str | None:
    if sdk_package == "sdk":
        return "base"
    if sdk_package == "sdk_hybrid":
        return "hybrid_cad"
    return None


def _parse_canonical_dataset_sequence(dataset_id: str, category_slug: str) -> int | None:
    match = re.fullmatch(rf"ds_{re.escape(category_slug)}_(\d{{4}})", dataset_id)
    if match is None:
        return None
    return int(match.group(1))


def _next_dataset_id(
    datasets: DatasetStore,
    *,
    category_slug: str,
    category: dict | None,
) -> tuple[str, int]:
    seen_dataset_ids = {
        str(entry.get("dataset_id") or "")
        for entry in datasets.list_entries()
        if isinstance(entry, dict)
    }
    highest_sequence = 0
    for dataset_id in seen_dataset_ids:
        sequence = _parse_canonical_dataset_sequence(dataset_id, category_slug)
        if sequence is not None:
            highest_sequence = max(highest_sequence, sequence)

    if isinstance(category, dict):
        for key in ("last_item_index", "current_count"):
            value = category.get(key)
            if isinstance(value, int):
                highest_sequence = max(highest_sequence, value)

    sequence = highest_sequence + 1
    dataset_id = f"ds_{category_slug}_{sequence:04d}"
    while dataset_id in seen_dataset_ids:
        sequence += 1
        dataset_id = f"ds_{category_slug}_{sequence:04d}"
    return dataset_id, sequence


def _upsert_category_metadata(
    repo: StorageRepo,
    queries: StorageQueries,
    *,
    record: dict,
    category_title: str,
    category_slug: str,
    now: str,
    sequence: int | None,
) -> dict:
    categories = CategoryStore(repo)
    existing = categories.load(category_slug)
    record_category_count = len(queries.list_record_ids_for_category(category_slug))
    run_count = len(queries.list_run_ids_for_category(category_slug))

    if isinstance(existing, dict):
        category = CategoryRecord(
            schema_version=int(existing.get("schema_version", 1)),
            slug=category_slug,
            title=str(existing.get("title") or category_title),
            description=str(existing.get("description") or ""),
            prompt_batch_ids=[
                str(batch_id)
                for batch_id in existing.get("prompt_batch_ids", [])
                if str(batch_id).strip()
            ],
            target_sdk_version=(
                str(existing.get("target_sdk_version"))
                if existing.get("target_sdk_version") is not None
                else _sdk_package_to_target_sdk_version(str(record.get("sdk_package") or ""))
            ),
            current_count=record_category_count,
            last_item_index=max(
                [
                    value
                    for value in (
                        sequence,
                        existing.get("last_item_index")
                        if isinstance(existing.get("last_item_index"), int)
                        else None,
                    )
                    if isinstance(value, int)
                ],
                default=None,
            ),
            created_at=str(existing.get("created_at") or now),
            updated_at=now,
            run_count=run_count,
        )
    else:
        category = CategoryRecord(
            schema_version=1,
            slug=category_slug,
            title=category_title,
            description="",
            prompt_batch_ids=[],
            target_sdk_version=_sdk_package_to_target_sdk_version(
                str(record.get("sdk_package") or "")
            ),
            current_count=record_category_count,
            last_item_index=sequence,
            created_at=now,
            updated_at=now,
            run_count=run_count,
        )
    categories.save(category)
    return category.to_dict()


def _promote_record_workflow(
    repo: StorageRepo,
    datasets: DatasetStore,
    queries: StorageQueries,
    *,
    record_ref: str,
    category_title: str,
    dataset_id: str | None,
    promoted_at: str,
) -> tuple[dict, dict, dict, object]:
    record_store = RecordStore(repo)
    collections = CollectionStore(repo)

    record_id = _resolve_record_reference(repo, record_ref)
    record = record_store.load_record(record_id)
    if not isinstance(record, dict):
        raise ValueError(f"Missing record.json for {record_id}")

    category_slug = _slugify_category_title(category_title)
    existing_entry = datasets.load_entry(record_id)
    used_sequence: int | None = None
    resolved_dataset_id = dataset_id

    if isinstance(existing_entry, dict):
        existing_category_slug = str(existing_entry.get("category_slug") or "")
        if existing_category_slug and existing_category_slug != category_slug:
            raise ValueError(
                f"Record already promoted under category {existing_category_slug}: {record_id}"
            )
        resolved_dataset_id = str(existing_entry.get("dataset_id") or "")
        used_sequence = _parse_canonical_dataset_sequence(resolved_dataset_id, category_slug)
        if not resolved_dataset_id:
            raise ValueError(f"Existing dataset entry missing dataset_id for {record_id}")
    else:
        if not resolved_dataset_id:
            category = CategoryStore(repo).load(category_slug)
            resolved_dataset_id, used_sequence = _next_dataset_id(
                datasets,
                category_slug=category_slug,
                category=category,
            )
        else:
            if datasets.find_record_id_by_dataset_id(resolved_dataset_id) is not None:
                raise ValueError(f"Dataset ID already exists: {resolved_dataset_id}")
            used_sequence = _parse_canonical_dataset_sequence(resolved_dataset_id, category_slug)

    record["category_slug"] = category_slug
    record["collections"] = ["dataset"]
    record["updated_at"] = promoted_at
    record_store.repo.write_json(repo.layout.record_metadata_path(record_id), record)

    source = record.get("source")
    run_id = str(source.get("run_id") or "") if isinstance(source, dict) else ""
    if run_id:
        run_path = repo.layout.run_metadata_path(run_id)
        run_metadata = repo.read_json(run_path)
        if isinstance(run_metadata, dict):
            run_metadata["category_slug"] = category_slug
            run_metadata["updated_at"] = promoted_at
            repo.write_json(run_path, run_metadata)

    if not isinstance(existing_entry, dict):
        datasets.promote_record(
            record_id=record_id,
            dataset_id=resolved_dataset_id,
            category_slug=category_slug,
            promoted_at=promoted_at,
        )

    collections.remove_workbench_entries(record_id)
    category = _upsert_category_metadata(
        repo,
        queries,
        record=record,
        category_title=category_title,
        category_slug=category_slug,
        now=promoted_at,
        sequence=used_sequence,
    )
    manifest = datasets.write_dataset_manifest()
    search_stats = SearchIndex(repo).rebuild()
    entry = datasets.load_entry(record_id)
    if not isinstance(entry, dict):
        raise ValueError(f"Failed to load dataset entry for {record_id}")
    return entry, category, manifest, search_stats


def _build_delete_record_preview(
    repo: StorageRepo,
    *,
    record_id: str | None,
    record_path: str | None,
) -> DeleteRecordPreview:
    if bool(record_id) == bool(record_path):
        raise ValueError("Provide exactly one of --record-id or --record-path")

    if record_path:
        record_dir = _resolve_record_path(repo, record_path)
        resolved_record_id = record_dir.name
    else:
        resolved_record_id = str(record_id)
        record_dir = repo.layout.record_dir(resolved_record_id).resolve()
        if not record_dir.is_dir():
            raise ValueError(f"Record not found: {resolved_record_id}")

    record = repo.read_json(repo.layout.record_metadata_path(resolved_record_id))
    if not isinstance(record, dict):
        raise ValueError(f"Missing record.json for {resolved_record_id}")

    display = record.get("display") if isinstance(record.get("display"), dict) else {}
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    dataset_entry = (
        repo.read_json(repo.layout.record_dataset_entry_path(resolved_record_id), default={}) or {}
    )
    workbench = CollectionStore(repo).load_workbench() or {}
    entries = workbench.get("entries", []) if isinstance(workbench, dict) else []
    in_workbench = any(
        str(entry.get("record_id") or "") == resolved_record_id
        for entry in entries
        if isinstance(entry, dict)
    )

    return DeleteRecordPreview(
        record_id=resolved_record_id,
        record_dir=record_dir,
        title=str(display.get("title") or ""),
        category_slug=str(record.get("category_slug") or ""),
        run_id=str(source.get("run_id") or ""),
        dataset_id=str(dataset_entry.get("dataset_id") or ""),
        in_workbench=in_workbench,
    )


def _print_delete_record_preview(preview: DeleteRecordPreview) -> None:
    print("Delete record preview")
    print(f"record_id={preview.record_id}")
    print(f"record_dir={preview.record_dir}")
    print(f"title={preview.title or '(untitled)'}")
    print(f"category_slug={preview.category_slug or '(none)'}")
    print(f"run_id={preview.run_id or '(none)'}")
    print(f"dataset_id={preview.dataset_id or '(none)'}")
    print(f"in_workbench={'yes' if preview.in_workbench else 'no'}")


def _build_prune_cache_preview(repo: StorageRepo) -> PruneCachePreview:
    cache_root = repo.layout.cache_root.resolve()
    protected_dirs = {
        cache_root,
        repo.layout.runs_root.resolve(),
        repo.layout.manifests_root.resolve(),
    }
    failed_staging_dirs: list[Path] = []
    failed_staging_dir_set: set[Path] = set()
    empty_dirs: list[Path] = []

    if repo.layout.runs_root.exists():
        for run_dir in repo.layout.runs_root.iterdir():
            if not run_dir.is_dir():
                continue
            results_path = repo.layout.run_results_path(run_dir.name)
            if not results_path.exists():
                continue
            with results_path.open(encoding="utf-8") as handle:
                for line in handle:
                    payload = line.strip()
                    if not payload:
                        continue
                    try:
                        row = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("status") or "").lower() != "failed":
                        continue
                    record_id = str(row.get("record_id") or "")
                    if not record_id:
                        continue
                    staging_dir = (repo.layout.run_staging_dir(run_dir.name) / record_id).resolve()
                    if not staging_dir.is_dir() or staging_dir in failed_staging_dir_set:
                        continue
                    failed_staging_dir_set.add(staging_dir)
                    failed_staging_dirs.append(staging_dir)

    def visit(path: Path) -> bool:
        resolved = path.resolve()
        if resolved in failed_staging_dir_set:
            return True
        has_persistent_content = False
        for child in path.iterdir():
            if child.is_dir():
                child_pruned = visit(child)
                if not child_pruned:
                    has_persistent_content = True
            else:
                has_persistent_content = True
        if has_persistent_content:
            return False
        if resolved not in protected_dirs:
            empty_dirs.append(path)
            return True
        return False

    if cache_root.exists():
        visit(cache_root)
    failed_staging_dirs.sort(key=lambda path: path.as_posix())
    empty_dirs.sort(key=lambda path: (len(path.relative_to(cache_root).parts), path.as_posix()))
    return PruneCachePreview(failed_staging_dirs=failed_staging_dirs, empty_dirs=empty_dirs)


def _print_prune_cache_preview(repo: StorageRepo, preview: PruneCachePreview) -> None:
    cache_root = repo.layout.cache_root.resolve()
    print("Prune cache preview")
    print(f"cache_root={cache_root}")
    print(f"failed_staging_dirs_to_remove={len(preview.failed_staging_dirs)}")
    print(f"empty_dirs_to_remove={len(preview.empty_dirs)}")
    if preview.failed_staging_dirs:
        for path in preview.failed_staging_dirs[:10]:
            print(f"sample_failed_staging_dir={path.relative_to(cache_root)}")
        remaining_failed = len(preview.failed_staging_dirs) - 10
        if remaining_failed > 0:
            print(f"sample_failed_staging_dirs_remaining={remaining_failed}")
    else:
        print("sample_failed_staging_dir=(none)")
    if preview.empty_dirs:
        for path in preview.empty_dirs[:10]:
            print(f"sample_dir={path.relative_to(cache_root)}")
        remaining = len(preview.empty_dirs) - 10
        if remaining > 0:
            print(f"sample_dirs_remaining={remaining}")
    else:
        print("sample_dir=(none)")


def _prune_cache(repo: StorageRepo, preview: PruneCachePreview) -> int:
    removed = 0
    for path in preview.failed_staging_dirs:
        if path.exists() and path.is_dir():
            shutil.rmtree(path)
            removed += 1
    for path in sorted(preview.empty_dirs, key=lambda item: len(item.parts), reverse=True):
        if path.exists() and path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            removed += 1
    return removed


def _delete_category(
    repo: StorageRepo, datasets: DatasetStore, preview: DeleteCategoryPreview
) -> tuple[dict, object]:
    categories = CategoryStore(repo)
    collections = CollectionStore(repo)
    records = RecordStore(repo)

    for record_id in preview.record_ids:
        record = records.load_record(record_id)
        source = record.get("source") if isinstance(record, dict) else None
        run_id = source.get("run_id") if isinstance(source, dict) else None

        collections.remove_workbench_entries(record_id)

        if isinstance(run_id, str) and run_id:
            for path in (
                repo.layout.run_staging_dir(run_id) / record_id,
                repo.layout.run_failures_dir(run_id) / record_id,
            ):
                if path.exists():
                    shutil.rmtree(path)

        records.delete_record(record_id)

    categories.delete(preview.category_slug)
    manifest = datasets.write_dataset_manifest()
    search_stats = SearchIndex(repo).rebuild()
    return manifest, search_stats


def _delete_record(
    repo: StorageRepo, datasets: DatasetStore, preview: DeleteRecordPreview
) -> tuple[dict, object]:
    collections = CollectionStore(repo)
    records = RecordStore(repo)

    collections.remove_workbench_entries(preview.record_id)

    if preview.run_id:
        for path in (
            repo.layout.run_staging_dir(preview.run_id) / preview.record_id,
            repo.layout.run_failures_dir(preview.run_id) / preview.record_id,
        ):
            if path.exists():
                shutil.rmtree(path)

    records.delete_record(preview.record_id)
    manifest = datasets.write_dataset_manifest()
    search_stats = SearchIndex(repo).rebuild()
    return manifest, search_stats


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="articraft-dataset")
    add_data_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-storage", help="Create the canonical data/ directory layout.")
    subparsers.add_parser("status", help="Show dataset storage status.")
    promote = subparsers.add_parser(
        "promote", help="Promote a record into the dataset with a record-local entry."
    )
    promote.add_argument("--record-id", required=True, help="Record identifier to promote.")
    promote.add_argument("--dataset-id", required=True, help="Stable dataset identifier to assign.")
    promote.add_argument(
        "--category-slug", help="Optional category slug override when the record lacks one."
    )
    promote.add_argument(
        "--promoted-at",
        help="UTC timestamp for promotion. Defaults to the current time.",
    )
    promote_record = subparsers.add_parser(
        "promote-record",
        help="Promote a saved record into the dataset, creating the category when needed.",
    )
    promote_record.add_argument(
        "record",
        help="Record ID or canonical record directory path under data/records/.",
    )
    promote_record.add_argument(
        "category_title",
        help="Category title to assign. The dataset slug is derived automatically.",
    )
    promote_record.add_argument(
        "--dataset-id",
        help="Optional dataset ID override. Defaults to the next canonical ds_<slug>_<NNNN> ID.",
    )
    promote_record.add_argument(
        "--promoted-at",
        help="UTC timestamp for promotion. Defaults to the current time.",
    )
    delete_category = subparsers.add_parser(
        "delete-category",
        help="Preview or delete an entire category and all records assigned to it.",
    )
    delete_category.add_argument(
        "--category-slug",
        required=True,
        help="Category slug to preview or delete.",
    )
    delete_category.add_argument(
        "--execute",
        action="store_true",
        help="Execute the deletion after the preview checks pass.",
    )
    delete_category.add_argument(
        "--confirm-slug",
        help="Exact category slug confirmation required when --execute is set.",
    )
    delete_record = subparsers.add_parser(
        "delete-record",
        help="Preview or delete a single record by ID or canonical record directory path.",
    )
    delete_record_target = delete_record.add_mutually_exclusive_group(required=True)
    delete_record_target.add_argument(
        "--record-id",
        help="Record identifier to preview or delete.",
    )
    delete_record_target.add_argument(
        "--record-path",
        help="Canonical record directory path under data/records/.",
    )
    delete_record.add_argument(
        "--execute",
        action="store_true",
        help="Execute the deletion after the preview checks pass.",
    )
    delete_record.add_argument(
        "--confirm-record-id",
        help="Exact record ID confirmation required when --execute is set.",
    )
    subparsers.add_parser("validate", help="Validate record-local dataset entries.")
    subparsers.add_parser(
        "build-manifest", help="Build the derived dataset manifest under data/cache/manifests/."
    )
    prune_cache = subparsers.add_parser(
        "prune-cache", help="Remove recursively empty directories under data/cache/."
    )
    prune_cache.add_argument(
        "--execute",
        action="store_true",
        help="Execute the prune after showing the preview.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    repo = StorageRepo(args.repo_root)
    datasets = DatasetStore(repo)
    queries = StorageQueries(repo)

    if args.command == "init-storage":
        repo.ensure_layout()
        print(f"Initialized dataset storage at {repo.layout.data_root}")
        return 0

    if args.command == "status":
        record_count = len(queries.list_record_ids())
        category_count = len(queries.list_category_slugs())
        dataset_entries = datasets.list_entries()
        print(
            f"records={record_count} categories={category_count} dataset_entries={len(dataset_entries)}"
        )
        return 0

    if args.command == "promote":
        repo.ensure_layout()
        try:
            entry = datasets.promote_record(
                record_id=args.record_id,
                dataset_id=args.dataset_id,
                category_slug=args.category_slug,
                promoted_at=args.promoted_at or _utc_now(),
            )
        except ValueError as exc:
            print(str(exc))
            return 1
        print(
            "Promoted "
            f"record_id={entry['record_id']} dataset_id={entry['dataset_id']} "
            f"at {repo.layout.record_dataset_entry_path(entry['record_id'])}"
        )
        return 0

    if args.command == "promote-record":
        repo.ensure_layout()
        try:
            entry, category, manifest, search_stats = _promote_record_workflow(
                repo,
                datasets,
                queries,
                record_ref=args.record,
                category_title=args.category_title,
                dataset_id=args.dataset_id,
                promoted_at=args.promoted_at or _utc_now(),
            )
        except ValueError as exc:
            print(str(exc))
            return 1
        print(
            f"Promoted record_id={entry['record_id']} "
            f"category_slug={entry['category_slug']} "
            f"dataset_id={entry['dataset_id']}"
        )
        print(
            f"Category title={category.get('title') or '(untitled)'} "
            f"path={repo.layout.category_metadata_path(entry['category_slug'])}"
        )
        print(
            f"Wrote dataset manifest to {repo.layout.dataset_manifest_path()} "
            f"entries={len(manifest['generated'])}"
        )
        print(
            f"Rebuilt search index at {search_stats.path} "
            f"records={search_stats.record_count} "
            f"categories={search_stats.category_count}"
        )
        return 0

    if args.command == "delete-category":
        repo.ensure_layout()
        preview = _build_delete_category_preview(repo, queries, args.category_slug)
        if preview is None:
            print(f"Category not found: {args.category_slug}")
            return 1

        _print_delete_category_preview(preview)
        if not args.execute:
            print(
                "Preview only. Re-run with "
                f"--execute --confirm-slug {preview.category_slug} "
                "to permanently delete this category."
            )
            return 0

        if args.confirm_slug != preview.category_slug:
            print(
                "Refusing to delete category: "
                f"--confirm-slug must exactly match {preview.category_slug}"
            )
            return 1

        manifest, search_stats = _delete_category(repo, datasets, preview)
        print(
            f"Deleted category_slug={preview.category_slug} "
            f"records_deleted={len(preview.record_ids)} "
            f"run_cache_entries_retained={len(preview.cached_run_ids)}"
        )
        print(
            f"Wrote dataset manifest to {repo.layout.dataset_manifest_path()} "
            f"entries={len(manifest['generated'])}"
        )
        print(
            f"Rebuilt search index at {search_stats.path} "
            f"records={search_stats.record_count} "
            f"categories={search_stats.category_count}"
        )
        return 0

    if args.command == "delete-record":
        repo.ensure_layout()
        try:
            preview = _build_delete_record_preview(
                repo,
                record_id=args.record_id,
                record_path=args.record_path,
            )
        except ValueError as exc:
            print(str(exc))
            return 1

        _print_delete_record_preview(preview)
        if not args.execute:
            print(
                "Preview only. Re-run with "
                f"--execute --confirm-record-id {preview.record_id} "
                "to permanently delete this record."
            )
            return 0

        if args.confirm_record_id != preview.record_id:
            print(
                "Refusing to delete record: "
                f"--confirm-record-id must exactly match {preview.record_id}"
            )
            return 1

        manifest, search_stats = _delete_record(repo, datasets, preview)
        print(
            f"Deleted record_id={preview.record_id} "
            f"category_slug={preview.category_slug or '(none)'} "
            f"run_id_retained={preview.run_id or '(none)'}"
        )
        print(
            f"Wrote dataset manifest to {repo.layout.dataset_manifest_path()} "
            f"entries={len(manifest['generated'])}"
        )
        print(
            f"Rebuilt search index at {search_stats.path} "
            f"records={search_stats.record_count} "
            f"categories={search_stats.category_count}"
        )
        return 0

    if args.command == "validate":
        errors = datasets.validate()
        if errors:
            for error in errors:
                print(error)
            return 1
        print(f"Dataset valid: entries={len(datasets.list_entries())}")
        return 0

    if args.command == "build-manifest":
        repo.ensure_layout()
        manifest = datasets.write_dataset_manifest()
        print(
            f"Wrote dataset manifest to {repo.layout.dataset_manifest_path()} entries={len(manifest['generated'])}"
        )
        return 0

    if args.command == "prune-cache":
        repo.ensure_layout()
        preview = _build_prune_cache_preview(repo)
        _print_prune_cache_preview(repo, preview)
        if not args.execute:
            print("Preview only. Re-run with --execute to remove these cache paths.")
            return 0

        removed = _prune_cache(repo, preview)
        print(f"Removed cache paths: {removed}")
        return 0

    parser.error(f"Unhandled command: {args.command}")
    return 2
