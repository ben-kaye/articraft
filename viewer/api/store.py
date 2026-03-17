from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from storage.collections import CollectionStore
from storage.datasets import DatasetStore
from storage.repo import StorageRepo
from viewer.api.schemas import (
    DatasetEntryResponse,
    RecordDetailResponse,
    RecordSummaryResponse,
    RunDetailResponse,
    RunResultResponse,
    RunSummaryResponse,
    ViewerBootstrapResponse,
    WorkbenchEntryResponse,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_sort_key(value: str | None) -> str:
    return value or ""


class ViewerStore:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.repo = StorageRepo(self.repo_root)
        self.repo.ensure_layout()
        self.collections = CollectionStore(self.repo)
        self.datasets = DatasetStore(self.repo)

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
        return rows

    def _record_summary(self, record_id: str) -> RecordSummaryResponse | None:
        record_path = self.repo.layout.record_metadata_path(record_id)
        record = self.repo.read_json(record_path)
        if record is None:
            return None

        display = record.get("display") or {}
        source = record.get("source") or {}
        artifacts = record.get("artifacts") or {}
        derived_assets = record.get("derived_assets") or {}
        record_dir = self.repo.layout.record_dir(record_id)

        compile_name = artifacts.get("compile_report_json") or "compile_report.json"
        provenance_name = artifacts.get("provenance_json") or "provenance.json"
        cost_name = artifacts.get("cost_json")

        return RecordSummaryResponse(
            record_id=record_id,
            title=str(display.get("title") or record_id),
            prompt_preview=str(display.get("prompt_preview") or ""),
            created_at=record.get("created_at"),
            updated_at=record.get("updated_at"),
            provider=record.get("provider"),
            model_id=record.get("model_id"),
            category_slug=record.get("category_slug"),
            run_id=source.get("run_id"),
            collections=[str(item) for item in record.get("collections", [])],
            materialization_status=derived_assets.get("materialization_status"),
            has_compile_report=(record_dir / str(compile_name)).exists(),
            has_provenance=(record_dir / str(provenance_name)).exists(),
            has_cost=(record_dir / str(cost_name)).exists() if cost_name else False,
        )

    def _record_detail(self, record_id: str) -> RecordDetailResponse | None:
        summary = self._record_summary(record_id)
        if summary is None:
            return None

        record = self.repo.read_json(self.repo.layout.record_metadata_path(record_id))
        if record is None:
            return None
        artifacts = record.get("artifacts") or {}
        record_dir = self.repo.layout.record_dir(record_id)
        compile_name = str(artifacts.get("compile_report_json") or "compile_report.json")
        provenance_name = str(artifacts.get("provenance_json") or "provenance.json")
        cost_name = artifacts.get("cost_json")
        compile_report = self.repo.read_json(record_dir / compile_name)
        provenance = self.repo.read_json(record_dir / provenance_name)
        cost = self.repo.read_json(record_dir / str(cost_name)) if cost_name else None

        return RecordDetailResponse(
            summary=summary,
            record=record,
            compile_report=compile_report,
            provenance=provenance,
            cost=cost,
        )

    def list_workbench_entries(self) -> list[WorkbenchEntryResponse]:
        workbench = self.collections.load_workbench() or {"entries": []}
        entries: list[WorkbenchEntryResponse] = []
        for item in workbench.get("entries", []):
            record_id = str(item.get("record_id", ""))
            if not record_id:
                continue
            entries.append(
                WorkbenchEntryResponse(
                    record_id=record_id,
                    added_at=str(item.get("added_at", "")),
                    label=item.get("label"),
                    tags=[str(tag) for tag in item.get("tags", [])],
                    archived=bool(item.get("archived", False)),
                    record=self._record_summary(record_id),
                )
            )
        return sorted(entries, key=lambda entry: _parse_sort_key(entry.added_at), reverse=True)

    def list_dataset_entries(self) -> list[DatasetEntryResponse]:
        entries: list[DatasetEntryResponse] = []
        for item in self.datasets.list_entries():
            record_id = str(item.get("record_id", ""))
            dataset_id = str(item.get("dataset_id", ""))
            category_slug = str(item.get("category_slug", ""))
            promoted_at = str(item.get("promoted_at", ""))
            if not record_id or not dataset_id:
                continue
            entries.append(
                DatasetEntryResponse(
                    record_id=record_id,
                    dataset_id=dataset_id,
                    category_slug=category_slug,
                    promoted_at=promoted_at,
                    record=self._record_summary(record_id),
                )
            )
        return entries

    def _run_summary(self, run_id: str, run_metadata: dict[str, Any]) -> RunSummaryResponse:
        results = self._read_jsonl(self.repo.layout.run_results_path(run_id))
        success_count = sum(1 for row in results if str(row.get("status", "")).lower() == "success")
        failed_count = sum(1 for row in results if str(row.get("status", "")).lower() == "failed")
        return RunSummaryResponse(
            run_id=run_id,
            run_mode=run_metadata.get("run_mode"),
            collection=run_metadata.get("collection"),
            status=run_metadata.get("status"),
            created_at=run_metadata.get("created_at"),
            updated_at=run_metadata.get("updated_at"),
            provider=run_metadata.get("provider"),
            model_id=run_metadata.get("model_id"),
            sdk_package=run_metadata.get("sdk_package"),
            prompt_count=run_metadata.get("prompt_count"),
            result_count=len(results),
            success_count=success_count,
            failed_count=failed_count,
        )

    def list_runs(self) -> list[RunSummaryResponse]:
        runs_root = self.repo.layout.runs_root
        if not runs_root.exists():
            return []

        summaries: list[RunSummaryResponse] = []
        for run_dir in runs_root.iterdir():
            if not run_dir.is_dir():
                continue
            run_id = run_dir.name
            run_metadata = self.repo.read_json(self.repo.layout.run_metadata_path(run_id))
            if not isinstance(run_metadata, dict):
                continue
            summaries.append(self._run_summary(run_id, run_metadata))

        return sorted(
            summaries,
            key=lambda item: (_parse_sort_key(item.updated_at), _parse_sort_key(item.created_at), item.run_id),
            reverse=True,
        )

    def load_run_detail(self, run_id: str) -> RunDetailResponse | None:
        run_metadata = self.repo.read_json(self.repo.layout.run_metadata_path(run_id))
        if not isinstance(run_metadata, dict):
            return None

        summary = self._run_summary(run_id, run_metadata)
        raw_results = self._read_jsonl(self.repo.layout.run_results_path(run_id))
        results: list[RunResultResponse] = []
        record_ids: list[str] = []
        for row in raw_results:
            record_id = row.get("record_id")
            if isinstance(record_id, str) and record_id and record_id not in record_ids:
                record_ids.append(record_id)
            results.append(
                RunResultResponse(
                    record_id=record_id if isinstance(record_id, str) else None,
                    status=row.get("status"),
                    message=row.get("message"),
                    turn_count=row.get("turn_count"),
                    tool_call_count=row.get("tool_call_count"),
                    compile_attempt_count=row.get("compile_attempt_count"),
                    record_dir=row.get("record_dir"),
                    staging_dir=row.get("staging_dir"),
                    raw=row,
                )
            )

        records: list[RecordDetailResponse] = []
        for record_id in record_ids:
            detail = self._record_detail(record_id)
            if detail is not None:
                records.append(detail)

        return RunDetailResponse(
            run=summary,
            run_metadata=run_metadata,
            results=results,
            records=records,
        )

    def bootstrap(self) -> ViewerBootstrapResponse:
        return ViewerBootstrapResponse(
            repo_root=self.repo_root.as_posix(),
            generated_at=_utc_now(),
            workbench_entries=self.list_workbench_entries(),
            dataset_entries=self.list_dataset_entries(),
            runs=self.list_runs(),
        )
