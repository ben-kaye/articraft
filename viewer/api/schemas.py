from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class RecordSummaryResponse(BaseModel):
    record_id: str
    title: str
    prompt_preview: str
    created_at: str | None = None
    updated_at: str | None = None
    provider: str | None = None
    model_id: str | None = None
    category_slug: str | None = None
    run_id: str | None = None
    collections: list[str] = []
    materialization_status: str | None = None
    has_compile_report: bool = False
    has_provenance: bool = False
    has_cost: bool = False


class WorkbenchEntryResponse(BaseModel):
    record_id: str
    added_at: str
    label: str | None = None
    tags: list[str] = []
    archived: bool = False
    record: RecordSummaryResponse | None = None


class DatasetEntryResponse(BaseModel):
    record_id: str
    dataset_id: str
    category_slug: str
    promoted_at: str
    record: RecordSummaryResponse | None = None


class RunSummaryResponse(BaseModel):
    run_id: str
    run_mode: str | None = None
    collection: str | None = None
    status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    provider: str | None = None
    model_id: str | None = None
    sdk_package: str | None = None
    prompt_count: int | None = None
    result_count: int = 0
    success_count: int = 0
    failed_count: int = 0


class RunResultResponse(BaseModel):
    record_id: str | None = None
    status: str | None = None
    message: str | None = None
    turn_count: int | None = None
    tool_call_count: int | None = None
    compile_attempt_count: int | None = None
    record_dir: str | None = None
    staging_dir: str | None = None
    raw: dict[str, Any] = {}


class RecordDetailResponse(BaseModel):
    summary: RecordSummaryResponse
    record: dict[str, Any] | None = None
    compile_report: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    cost: dict[str, Any] | None = None


class RunDetailResponse(BaseModel):
    run: RunSummaryResponse
    run_metadata: dict[str, Any]
    results: list[RunResultResponse]
    records: list[RecordDetailResponse]


class ViewerBootstrapResponse(BaseModel):
    repo_root: str
    generated_at: str
    workbench_entries: list[WorkbenchEntryResponse]
    dataset_entries: list[DatasetEntryResponse]
    runs: list[RunSummaryResponse]
