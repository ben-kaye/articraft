from __future__ import annotations

import argparse
import json
import platform
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from agent.compiler import compile_urdf_report, compile_urdf_report_maybe_timeout
from performance.corpus import DEFAULT_CASE_IDS, BenchmarkCase, get_cases

DEFAULT_RESULTS_DIR = Path("performance/results")
DEPENDENCY_NAMES = ("numpy", "trimesh", "coacd", "python-fcl", "cadquery", "rich")


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    case_id: str
    label: str
    record_id: str
    source_script: str
    sdk_package: str
    cache_mode: str
    compile_mode: str
    iterations: int
    durations_ms: list[float]
    median_ms: float | None
    success_count: int
    warning_counts: list[int]
    urdf_sizes: list[int]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_timestamp(value: datetime | None = None) -> str:
    resolved = value or _utc_now()
    return resolved.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _sanitize_label(value: str | None) -> str:
    if not value:
        return "run"
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    collapsed = "-".join(part for part in cleaned.split("-") if part)
    return collapsed or "run"


def _git_capture(repo_root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return completed.stdout.strip() or None


def _git_metadata(repo_root: Path) -> dict[str, Any]:
    commit = _git_capture(repo_root, "rev-parse", "HEAD")
    branch = _git_capture(repo_root, "branch", "--show-current")
    status = _git_capture(repo_root, "status", "--short")
    return {
        "commit": commit,
        "short_commit": commit[:8] if commit else None,
        "branch": branch,
        "is_dirty": bool(status),
    }


def _dependency_versions() -> dict[str, str]:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except Exception:
        return {}

    resolved: dict[str, str] = {}
    for name in DEPENDENCY_NAMES:
        try:
            resolved[name] = version(name)
        except PackageNotFoundError:
            continue
    return resolved


def _environment_metadata() -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "dependency_versions": _dependency_versions(),
    }


def _stage_case(case: BenchmarkCase, repo_root: Path, temp_root: Path) -> Path:
    source_dir = case.source_record_dir(repo_root)
    if not source_dir.exists():
        raise FileNotFoundError(f"Benchmark source record does not exist: {source_dir}")
    destination = temp_root / case.record_id
    shutil.copytree(
        source_dir,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    return destination / "model.py"


def _compile_once(script_path: Path, *, sdk_package: str, compile_mode: str) -> tuple[int, int]:
    if compile_mode == "direct":
        report = compile_urdf_report(script_path, sdk_package=sdk_package)
    elif compile_mode == "timeout":
        report = compile_urdf_report_maybe_timeout(script_path, sdk_package=sdk_package)
    else:
        raise ValueError(f"Unsupported compile mode: {compile_mode}")
    return len(report.warnings), len(report.urdf_xml.encode("utf-8"))


def _benchmark_scenario(
    *,
    repo_root: Path,
    case: BenchmarkCase,
    cache_mode: str,
    compile_mode: str,
    iterations: int,
) -> ScenarioResult:
    durations_ms: list[float] = []
    warning_counts: list[int] = []
    urdf_sizes: list[int] = []
    errors: list[str] = []
    success_count = 0

    if cache_mode == "warm":
        with tempfile.TemporaryDirectory(prefix=f"articraft-perf-{case.case_id}-") as temp_dir:
            staged_script = _stage_case(case, repo_root, Path(temp_dir))
            for _ in range(iterations):
                start = time.perf_counter()
                try:
                    warning_count, urdf_size = _compile_once(
                        staged_script,
                        sdk_package=case.sdk_package,
                        compile_mode=compile_mode,
                    )
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
                else:
                    success_count += 1
                    warning_counts.append(warning_count)
                    urdf_sizes.append(urdf_size)
                durations_ms.append((time.perf_counter() - start) * 1000.0)
    elif cache_mode == "cold":
        for _ in range(iterations):
            with tempfile.TemporaryDirectory(prefix=f"articraft-perf-{case.case_id}-") as temp_dir:
                staged_script = _stage_case(case, repo_root, Path(temp_dir))
                start = time.perf_counter()
                try:
                    warning_count, urdf_size = _compile_once(
                        staged_script,
                        sdk_package=case.sdk_package,
                        compile_mode=compile_mode,
                    )
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
                else:
                    success_count += 1
                    warning_counts.append(warning_count)
                    urdf_sizes.append(urdf_size)
                durations_ms.append((time.perf_counter() - start) * 1000.0)
    else:
        raise ValueError(f"Unsupported cache mode: {cache_mode}")

    median_ms = statistics.median(durations_ms) if durations_ms else None
    return ScenarioResult(
        case_id=case.case_id,
        label=case.label,
        record_id=case.record_id,
        source_script=case.script_relpath,
        sdk_package=case.sdk_package,
        cache_mode=cache_mode,
        compile_mode=compile_mode,
        iterations=iterations,
        durations_ms=[round(value, 3) for value in durations_ms],
        median_ms=round(median_ms, 3) if median_ms is not None else None,
        success_count=success_count,
        warning_counts=warning_counts,
        urdf_sizes=urdf_sizes,
        errors=errors,
    )


def _build_output_path(
    *,
    output_dir: Path,
    created_at: datetime,
    git_meta: dict[str, Any],
    label: str | None,
) -> Path:
    short_commit = str(git_meta.get("short_commit") or "nogit")
    day_dir = output_dir / created_at.strftime("%Y-%m-%d")
    filename = (
        f"{created_at.strftime('%Y%m%dT%H%M%SZ')}_{short_commit}_{_sanitize_label(label)}.json"
    )
    return day_dir / filename


def _run_payload(
    *,
    repo_root: Path,
    created_at: datetime,
    label: str | None,
    args: argparse.Namespace,
    cases: list[BenchmarkCase],
    results: list[ScenarioResult],
) -> dict[str, Any]:
    git_meta = _git_metadata(repo_root)
    total_median_ms = round(
        sum(result.median_ms or 0.0 for result in results),
        3,
    )
    return {
        "schema_version": 1,
        "created_at": _utc_timestamp(created_at),
        "label": label,
        "git": git_meta,
        "environment": _environment_metadata(),
        "config": {
            "case_ids": [case.case_id for case in cases],
            "cache_modes": _split_csv(args.cache_modes),
            "compile_modes": _split_csv(args.compile_modes),
            "iterations": args.iterations,
        },
        "results": [result.to_dict() for result in results],
        "summary": {
            "scenario_count": len(results),
            "failure_count": sum(1 for result in results if result.errors),
            "total_median_ms": total_median_ms,
        },
    }


def _print_case_list(console: Console, cases: list[BenchmarkCase]) -> None:
    table = Table(title="Performance Corpus")
    table.add_column("Case ID")
    table.add_column("Label")
    table.add_column("Record ID")
    table.add_column("Notes")
    for case in cases:
        table.add_row(case.case_id, case.label, case.record_id, case.notes)
    console.print(table)


def _print_results(console: Console, results: list[ScenarioResult]) -> None:
    table = Table(title="Performance Results")
    table.add_column("Case")
    table.add_column("Cache")
    table.add_column("Compile")
    table.add_column("Median (ms)", justify="right")
    table.add_column("Success", justify="right")
    table.add_column("Warnings", justify="right")
    table.add_column("Status")
    for result in results:
        warning_total = sum(result.warning_counts)
        status = "ok" if not result.errors else result.errors[0]
        table.add_row(
            result.case_id,
            result.cache_mode,
            result.compile_mode,
            f"{result.median_ms:.3f}" if result.median_ms is not None else "-",
            f"{result.success_count}/{result.iterations}",
            str(warning_total),
            status,
        )
    console.print(table)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m performance")
    parser.add_argument(
        "--case",
        dest="cases",
        action="append",
        help=f"Benchmark case id to run. Repeatable. Defaults to all: {', '.join(DEFAULT_CASE_IDS)}.",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="List the curated benchmark corpus and exit.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Number of iterations per scenario.",
    )
    parser.add_argument(
        "--cache-modes",
        default="warm,cold",
        help="Comma-separated cache modes to run: warm, cold.",
    )
    parser.add_argument(
        "--compile-modes",
        default="direct,timeout",
        help="Comma-separated compile modes to run: direct, timeout.",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Persist the benchmark run as JSON under performance/results by default.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="Directory for saved benchmark result JSON files.",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Optional short label to include in saved result filenames and payloads.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    console = Console()
    repo_root = _repo_root()

    try:
        cases = get_cases(args.cases)
    except KeyError as exc:
        parser.error(str(exc))

    if args.list_cases:
        _print_case_list(console, cases)
        return 0

    if args.iterations <= 0:
        parser.error("--iterations must be positive")

    cache_modes = _split_csv(args.cache_modes)
    compile_modes = _split_csv(args.compile_modes)
    valid_cache_modes = {"warm", "cold"}
    valid_compile_modes = {"direct", "timeout"}
    invalid_cache_modes = [mode for mode in cache_modes if mode not in valid_cache_modes]
    invalid_compile_modes = [mode for mode in compile_modes if mode not in valid_compile_modes]
    if not cache_modes or invalid_cache_modes:
        parser.error("cache modes must be a comma-separated subset of: warm, cold")
    if not compile_modes or invalid_compile_modes:
        parser.error("compile modes must be a comma-separated subset of: direct, timeout")

    created_at = _utc_now()
    results: list[ScenarioResult] = []
    for case in cases:
        for cache_mode in cache_modes:
            for compile_mode in compile_modes:
                console.print(
                    f"Running `{case.case_id}` cache=`{cache_mode}` compile=`{compile_mode}` "
                    f"({args.iterations} iteration(s))"
                )
                results.append(
                    _benchmark_scenario(
                        repo_root=repo_root,
                        case=case,
                        cache_mode=cache_mode,
                        compile_mode=compile_mode,
                        iterations=args.iterations,
                    )
                )

    _print_results(console, results)

    payload = _run_payload(
        repo_root=repo_root,
        created_at=created_at,
        label=args.label,
        args=args,
        cases=cases,
        results=results,
    )

    if args.save:
        output_path = _build_output_path(
            output_dir=(repo_root / args.output_dir).resolve()
            if not args.output_dir.is_absolute()
            else args.output_dir.resolve(),
            created_at=created_at,
            git_meta=payload["git"],
            label=args.label,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        console.print(f"Saved benchmark results to {output_path}")

    return 1 if any(result.errors for result in results) else 0
