from __future__ import annotations

from pathlib import Path

from performance.corpus import DEFAULT_CASE_IDS, DEFAULT_CORPUS, get_cases


def test_default_case_ids_are_unique() -> None:
    assert len(DEFAULT_CASE_IDS) == len(set(DEFAULT_CASE_IDS))


def test_default_corpus_points_to_existing_model_scripts() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    for case in DEFAULT_CORPUS:
        assert case.source_script(repo_root).exists(), case.case_id


def test_get_cases_returns_requested_subset_in_order() -> None:
    selected = get_cases(["mixed_small", "stress_heavy"])
    assert [case.case_id for case in selected] == ["mixed_small", "stress_heavy"]
