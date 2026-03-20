from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    label: str
    record_id: str
    script_relpath: str
    sdk_package: str = "sdk"
    notes: str = ""

    def source_script(self, repo_root: Path) -> Path:
        return (repo_root / self.script_relpath).resolve()

    def source_record_dir(self, repo_root: Path) -> Path:
        return self.source_script(repo_root).parent


DEFAULT_CORPUS: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        case_id="primitive_small",
        label="Bench Vise",
        record_id="rec_bench_vise_with_prismatic_jaw_0001",
        script_relpath="data/records/rec_bench_vise_with_prismatic_jaw_0001/model.py",
        notes="Small primitive-first baseline with a simple prismatic articulation.",
    ),
    BenchmarkCase(
        case_id="mixed_small",
        label="Router With Antennas",
        record_id="rec_a-realistic-model-of-an-internet-router-with-4-a_20260319_144436_012112_dbdd0d7d",
        script_relpath=(
            "data/records/"
            "rec_a-realistic-model-of-an-internet-router-with-4-a_20260319_144436_012112_dbdd0d7d/model.py"
        ),
        notes="Small realistic object with one generated shell mesh and multiple antenna joints.",
    ),
    BenchmarkCase(
        case_id="mixed_medium",
        label="Blender",
        record_id="rec_blender_0001",
        script_relpath="data/records/rec_blender_0001/model.py",
        notes="Medium mixed mesh-plus-primitive appliance with a representative hinged assembly.",
    ),
    BenchmarkCase(
        case_id="articulated_medium",
        label="Robotic Arm",
        record_id="rec_a-realistic-model-of-a-robotic-arm-that-is-fully_20260319_025530_865163_179489fc",
        script_relpath=(
            "data/records/"
            "rec_a-realistic-model-of-a-robotic-arm-that-is-fully_20260319_025530_865163_179489fc/model.py"
        ),
        notes="Articulated chain benchmark with multiple exported meshes and several joints.",
    ),
    BenchmarkCase(
        case_id="mixed_heavy",
        label="Transport Wheelchair",
        record_id="rec_transport_wheelchair_0001",
        script_relpath="data/records/rec_transport_wheelchair_0001/model.py",
        notes="Heavier realistic mobility case with many generated meshes and articulations.",
    ),
    BenchmarkCase(
        case_id="stress_heavy",
        label="Stationary Exercise Bike",
        record_id="rec_stationary_exercise_bike_0001",
        script_relpath="data/records/rec_stationary_exercise_bike_0001/model.py",
        notes="Large end-to-end stress case with lots of geometry and many mesh exports.",
    ),
)

DEFAULT_CASE_IDS: tuple[str, ...] = tuple(case.case_id for case in DEFAULT_CORPUS)
_CASES_BY_ID = {case.case_id: case for case in DEFAULT_CORPUS}


def get_cases(case_ids: list[str] | None = None) -> list[BenchmarkCase]:
    if not case_ids:
        return list(DEFAULT_CORPUS)

    resolved: list[BenchmarkCase] = []
    missing: list[str] = []
    for case_id in case_ids:
        case = _CASES_BY_ID.get(case_id)
        if case is None:
            missing.append(case_id)
        else:
            resolved.append(case)

    if missing:
        available = ", ".join(DEFAULT_CASE_IDS)
        raise KeyError(f"Unknown benchmark case(s): {', '.join(missing)}. Available: {available}")
    return resolved
