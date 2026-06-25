"""Pydantic models for stored records. Validation comes free; domain rules live in tests."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Lineage(BaseModel):
    origin_record_id: str | None = None  # root ancestor
    parent_record_id: str | None = None  # direct parent (set on fork)


class Cost(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0  # prompt-cache hits (subset of input_tokens)
    total_usd: float = 0.0


class Provenance(BaseModel):
    """How the record was generated. Written once at creation."""

    model: str
    protocol: str | None = None
    thinking_level: str | None = None
    sdk_package: str = "sdk"
    max_turns: int | None = None
    turn_count: int | None = None
    base_url: str | None = None
    creator_mode: str = "internal"  # internal | external_agent
    agent: str | None = None


class Record(BaseModel):
    """Canonical metadata for one generated model. Persisted as record.json."""

    record_id: str
    created_at: str
    updated_at: str
    prompt: str
    title: str = ""
    category_slug: str | None = None
    collections: list[str] = Field(default_factory=lambda: ["workbench"])
    dataset_id: str | None = None
    model: str = ""
    ratings: dict[str, int] = Field(default_factory=dict)  # {rater_name: 1-5}
    lineage: Lineage = Field(default_factory=Lineage)
    cost: Cost = Field(default_factory=Cost)
    prompt_sha256: str = ""
    model_py_sha256: str = ""
    has_urdf: bool = False
    compile_ok: bool = False
    status: str = "done"  # running | done | failed
    code_git: str = ""  # harness git HEAD at generation, "<sha>" or "<sha>-dirty"


def avg_rating(ratings: dict[str, int]) -> float | None:
    return round(sum(ratings.values()) / len(ratings), 1) if ratings else None


class RunResult(BaseModel):
    key: str  # dedup key, e.g. prompt index
    record_id: str | None = None
    status: str  # done | failed | pending
    error: str | None = None


class Run(BaseModel):
    """Batch generation run state. Persisted as run.json; results in results.jsonl."""

    run_id: str
    created_at: str
    status: str = "running"  # running | done | failed
    spec_path: str | None = None
    total: int = 0
