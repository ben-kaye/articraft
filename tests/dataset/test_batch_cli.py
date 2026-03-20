from __future__ import annotations

import asyncio
import csv
import json
import threading
from pathlib import Path

import pytest

from agent import batch_runner
from agent.models import AgentResult, TerminateReason
from cli.dataset import main as dataset_main
from storage.categories import CategoryStore
from storage.models import CategoryRecord
from storage.queries import StorageQueries
from storage.repo import StorageRepo
from viewer.api.store import ViewerStore


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class SuccessBatchAgent:
    active = 0
    max_active = 0

    def __init__(
        self,
        *,
        file_path: str,
        trace_dir: str | None = None,
        provider: str = "openai",
        model_id: str | None = None,
        **_: object,
    ) -> None:
        self.file_path = Path(file_path)
        self.trace_dir = Path(trace_dir) if trace_dir else None
        self.provider = provider
        self.loaded_system_prompt_path = "designer_system_prompt.txt"
        self.llm = type("LLM", (), {"model_id": model_id or "gpt-5.4"})()

    async def __aenter__(self) -> "SuccessBatchAgent":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def run(self, user_content: object) -> AgentResult:
        type(self).active += 1
        type(self).max_active = max(type(self).max_active, type(self).active)
        try:
            await asyncio.sleep(0.05)
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self.file_path.write_text(
                "from __future__ import annotations\n\nobject_model = None\n",
                encoding="utf-8",
            )
            (self.file_path.parent / "assets" / "meshes").mkdir(parents=True, exist_ok=True)
            (self.file_path.parent / "assets" / "meshes" / "part.obj").write_text(
                "# mesh\n",
                encoding="utf-8",
            )
            (self.file_path.parent / "cost.json").write_text(
                json.dumps({"total": {"costs_usd": {"total": 0.1}}}, indent=2),
                encoding="utf-8",
            )
            if self.trace_dir is not None:
                self.trace_dir.mkdir(parents=True, exist_ok=True)
                (self.trace_dir / "conversation.jsonl").write_text(
                    '{"type":"message","message":{"role":"assistant","content":"done"}}\n',
                    encoding="utf-8",
                )
            return AgentResult(
                success=True,
                reason=TerminateReason.CODE_VALID,
                message="done",
                conversation=[{"role": "user", "content": user_content}],
                final_code=self.file_path.read_text(encoding="utf-8"),
                urdf_xml="<robot name='batch'/>",
                compile_warnings=[],
                turn_count=3,
                tool_call_count=4,
                compile_attempt_count=1,
                usage=None,
            )
        finally:
            type(self).active -= 1


class FlakyBatchAgent(SuccessBatchAgent):
    attempts_by_record: dict[str, int] = {}

    async def run(self, user_content: object) -> AgentResult:
        record_id = self.file_path.parent.name
        self.attempts_by_record[record_id] = self.attempts_by_record.get(record_id, 0) + 1
        if "retry" in str(user_content).lower() and self.attempts_by_record[record_id] == 1:
            await asyncio.sleep(0.05)
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self.file_path.write_text("# failed\n", encoding="utf-8")
            return AgentResult(
                success=False,
                reason=TerminateReason.MAX_TURNS,
                message="synthetic failure",
                conversation=[{"role": "user", "content": user_content}],
                final_code=None,
                urdf_xml=None,
                compile_warnings=[],
                turn_count=1,
                tool_call_count=1,
                compile_attempt_count=1,
                usage=None,
            )
        return await super().run(user_content)


@pytest.fixture(autouse=True)
def reset_agents() -> None:
    SuccessBatchAgent.active = 0
    SuccessBatchAgent.max_active = 0
    FlakyBatchAgent.active = 0
    FlakyBatchAgent.max_active = 0
    FlakyBatchAgent.attempts_by_record = {}


def test_build_batch_config_validates_csv_rows(tmp_path: Path) -> None:
    repo = StorageRepo(tmp_path)
    repo.ensure_layout()
    CategoryStore(repo).save(
        CategoryRecord(schema_version=1, slug="hinge", title="Hinge", description="")
    )

    cases = [
        (
            [
                {
                    "row_id": "a",
                    "category_slug": "new_cat",
                    "prompt": "x",
                    "provider": "openai",
                    "model_id": "gpt-5.4",
                    "thinking_level": "high",
                    "max_turns": "10",
                    "sdk_package": "sdk",
                }
            ],
            "without category_title",
        ),
        (
            [
                {
                    "row_id": "dup",
                    "category_slug": "hinge",
                    "category_title": "Hinge",
                    "prompt": "x",
                    "provider": "openai",
                    "model_id": "gpt-5.4",
                    "thinking_level": "high",
                    "max_turns": "10",
                    "sdk_package": "sdk",
                },
                {
                    "row_id": "dup",
                    "category_slug": "hinge",
                    "category_title": "Hinge",
                    "prompt": "y",
                    "provider": "openai",
                    "model_id": "gpt-5.4",
                    "thinking_level": "high",
                    "max_turns": "10",
                    "sdk_package": "sdk",
                },
            ],
            "Duplicate row_id",
        ),
        (
            [
                {
                    "row_id": "a",
                    "category_slug": "hinge",
                    "category_title": "Hinge",
                    "prompt": "x",
                    "provider": "gemini",
                    "model_id": "gpt-5.4",
                    "thinking_level": "high",
                    "max_turns": "10",
                    "sdk_package": "sdk",
                }
            ],
            "provider/model mismatch",
        ),
        (
            [
                {
                    "row_id": "a",
                    "category_slug": "hinge",
                    "category_title": "Wrong",
                    "prompt": "x",
                    "provider": "openai",
                    "model_id": "gpt-5.4",
                    "thinking_level": "high",
                    "max_turns": "10",
                    "sdk_package": "sdk",
                }
            ],
            "category_title mismatch",
        ),
        (
            [
                {
                    "row_id": "a",
                    "category_slug": "hinge",
                    "category_title": "Hinge",
                    "prompt": "x",
                    "provider": "openai",
                    "model_id": "gpt-5.4",
                    "thinking_level": "high",
                    "max_turns": "0",
                    "sdk_package": "sdk",
                }
            ],
            "max_turns > 0",
        ),
    ]

    for index, (rows, message) in enumerate(cases, start=1):
        spec_path = tmp_path / f"invalid_{index}.csv"
        _write_csv(spec_path, rows)
        with pytest.raises(ValueError, match=message):
            batch_runner.build_batch_config(
                repo_root=tmp_path,
                spec_arg=str(spec_path),
                concurrency=2,
                system_prompt_path="designer_system_prompt.txt",
                sdk_docs_mode="full",
                qc_blurb_path=None,
                resume=False,
                resume_policy="failed_or_pending",
                keep_awake=False,
                pause_file=None,
                pause_poll_seconds=1.0,
                keyboard_pause_enabled=False,
            )


def test_build_batch_config_resolves_auto_concurrency_to_logical_cpu_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = StorageRepo(tmp_path)
    repo.ensure_layout()
    CategoryStore(repo).save(
        CategoryRecord(schema_version=1, slug="hinge", title="Hinge", description="")
    )

    spec_path = tmp_path / "source_specs" / "auto_batch.csv"
    _write_csv(
        spec_path,
        [
            {
                "row_id": f"row_{index}",
                "category_slug": "hinge",
                "category_title": "Hinge",
                "prompt": f"make hinge {index}",
                "provider": "openai",
                "model_id": "gpt-5.4",
                "thinking_level": "high",
                "max_turns": "10",
                "sdk_package": "sdk",
            }
            for index in range(1, 9)
        ],
    )
    monkeypatch.setattr(batch_runner, "_logical_cpu_count", lambda: 6)

    config = batch_runner.build_batch_config(
        repo_root=tmp_path,
        spec_arg=str(spec_path),
        concurrency="auto",
        system_prompt_path="designer_system_prompt.txt",
        sdk_docs_mode="full",
        qc_blurb_path=None,
        resume=False,
        resume_policy="failed_or_pending",
        keep_awake=False,
        pause_file=None,
        pause_poll_seconds=1.0,
        keyboard_pause_enabled=False,
    )

    assert config.concurrency == 6


def test_run_batch_persists_records_and_batch_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(batch_runner, "ArticraftAgent", SuccessBatchAgent)

    thread_ids: list[int] = []
    original_write_success_record = batch_runner._write_success_record

    def wrapped_write_success_record(*args: object, **kwargs: object) -> Path:
        thread_ids.append(threading.get_ident())
        return original_write_success_record(*args, **kwargs)

    monkeypatch.setattr(batch_runner, "_write_success_record", wrapped_write_success_record)

    spec_path = tmp_path / "source_specs" / "mixed_batch.csv"
    _write_csv(
        spec_path,
        [
            {
                "row_id": "hinge_row",
                "category_slug": "hinge",
                "category_title": "Hinge",
                "prompt": "make a hinge",
                "provider": "openai",
                "model_id": "gpt-5.4",
                "thinking_level": "high",
                "max_turns": "12",
                "sdk_package": "sdk",
            },
            {
                "row_id": "fan_row",
                "category_slug": "fan",
                "category_title": "Fan",
                "prompt": "make a fan",
                "provider": "gemini",
                "model_id": "gemini-3-flash-preview",
                "thinking_level": "low",
                "max_turns": "8",
                "sdk_package": "sdk_hybrid",
            },
        ],
    )

    exit_code = dataset_main(
        [
            "--repo-root",
            str(tmp_path),
            "run-batch",
            str(spec_path),
            "--concurrency",
            "2",
        ]
    )
    assert exit_code == 0
    assert SuccessBatchAgent.max_active >= 2
    assert thread_ids
    assert all(thread_id != threading.main_thread().ident for thread_id in thread_ids)

    repo = StorageRepo(tmp_path)
    copied_spec = repo.layout.batch_spec_path("mixed_batch")
    assert copied_spec.exists()

    run_dirs = sorted(path for path in repo.layout.runs_root.iterdir() if path.is_dir())
    assert len(run_dirs) == 1
    run_id = run_dirs[0].name
    run_payload = repo.read_json(repo.layout.run_metadata_path(run_id))
    assert run_payload["run_mode"] == "dataset_batch"
    assert run_payload["provider"] == "mixed"
    assert run_payload["model_id"] == "mixed"
    assert run_payload["sdk_package"] == "mixed"
    assert run_payload["batch_spec_id"] == "mixed_batch"
    assert sorted(run_payload["category_slugs"]) == ["fan", "hinge"]
    assert run_payload["status"] == "success"

    result_rows = [
        json.loads(line)
        for line in repo.layout.run_results_path(run_id).read_text(encoding="utf-8").splitlines()
    ]
    assert len(result_rows) == 2
    assert sorted(row["row_id"] for row in result_rows) == ["fan_row", "hinge_row"]

    hinge_record = repo.read_json(repo.layout.record_metadata_path("rec_hinge_0001"))
    fan_record = repo.read_json(repo.layout.record_metadata_path("rec_fan_0001"))
    assert hinge_record["source"]["run_id"] == run_id
    assert hinge_record["source"]["batch_spec_id"] == "mixed_batch"
    assert hinge_record["source"]["row_id"] == "hinge_row"
    assert hinge_record["source"]["prompt_index"] == 1
    assert fan_record["source"]["row_id"] == "fan_row"
    assert fan_record["sdk_package"] == "sdk_hybrid"

    queries = StorageQueries(repo)
    assert run_id in queries.list_run_ids_for_category("hinge")
    assert run_id in queries.list_run_ids_for_category("fan")

    viewer_store = ViewerStore(tmp_path)
    run_detail = viewer_store.load_run_detail(run_id)
    assert run_detail is not None
    assert run_detail.run.status == "success"
    assert len(run_detail.results) == 2
    assert {item.raw["row_id"] for item in run_detail.results} == {"hinge_row", "fan_row"}


def test_run_batch_resume_reuses_allocations_and_only_reruns_failed_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(batch_runner, "ArticraftAgent", FlakyBatchAgent)

    spec_path = tmp_path / "source_specs" / "resume_batch.csv"
    _write_csv(
        spec_path,
        [
            {
                "row_id": "ok_row",
                "category_slug": "hinge",
                "category_title": "Hinge",
                "prompt": "make a hinge",
                "provider": "openai",
                "model_id": "gpt-5.4",
                "thinking_level": "high",
                "max_turns": "12",
                "sdk_package": "sdk",
            },
            {
                "row_id": "retry_row",
                "category_slug": "hinge",
                "category_title": "Hinge",
                "prompt": "retry hinge once",
                "provider": "openai",
                "model_id": "gpt-5.4",
                "thinking_level": "high",
                "max_turns": "12",
                "sdk_package": "sdk",
            },
            {
                "category_slug": "fan",
                "category_title": "Fan",
                "prompt": "make a fan",
                "provider": "gemini",
                "model_id": "gemini-3-flash-preview",
                "thinking_level": "low",
                "max_turns": "8",
                "sdk_package": "sdk_hybrid",
            },
        ],
    )

    first_exit_code = dataset_main(
        [
            "--repo-root",
            str(tmp_path),
            "run-batch",
            str(spec_path),
            "--concurrency",
            "3",
        ]
    )
    assert first_exit_code == 1
    assert FlakyBatchAgent.max_active >= 2

    repo = StorageRepo(tmp_path)
    run_id = next(path.name for path in repo.layout.runs_root.iterdir() if path.is_dir())
    allocations = repo.read_json(repo.layout.run_allocations_path(run_id))
    assert allocations is not None
    allocations_by_row = {row["row_id"]: row for row in allocations["rows"]}
    failed_record_id = allocations_by_row["retry_row"]["record_id"]
    failed_dataset_id = allocations_by_row["retry_row"]["dataset_id"]

    first_results = [
        json.loads(line)
        for line in repo.layout.run_results_path(run_id).read_text(encoding="utf-8").splitlines()
    ]
    assert len(first_results) == 3
    assert next(row for row in first_results if row["row_id"] == "retry_row")["status"] == "failed"

    second_exit_code = dataset_main(
        [
            "--repo-root",
            str(tmp_path),
            "run-batch",
            str(spec_path),
            "--concurrency",
            "3",
            "--resume",
        ]
    )
    assert second_exit_code == 0

    second_results = [
        json.loads(line)
        for line in repo.layout.run_results_path(run_id).read_text(encoding="utf-8").splitlines()
    ]
    assert len(second_results) == 3
    retry_row = next(row for row in second_results if row["row_id"] == "retry_row")
    assert retry_row["status"] == "success"
    assert retry_row["record_id"] == failed_record_id
    assert retry_row["dataset_id"] == failed_dataset_id

    retry_state = repo.read_json(repo.layout.run_row_state_path(run_id, "retry_row"))
    assert retry_state["latest_status"] == "success"
    assert retry_state["attempt_count"] == 2

    record = repo.read_json(repo.layout.record_metadata_path(failed_record_id))
    assert record["source"]["row_id"] == "retry_row"
    assert record["source"]["run_id"] == run_id
