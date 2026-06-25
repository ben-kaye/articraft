"""Turn a CompileResult into a short feedback message for the LLM.

The SDK already produces structured errors/failures/warnings; we just format them — and tag each
with a `(kind, group)` so failures are comparable across runs (the categories an ICL study wants:
"real_overlap" vs "exact_contact_gap" vs "model_validity", not free prose).

This is a thin re-introduction of the old `../articraft` `CompileSignal` taxonomy (which carried
severity/kind/code/group/blocking/dedupe over 40+ specs). We keep only the two axes that make
failures comparable — `kind` (fine) and `group` (coarse) — and derive them from the stable SDK
check-helper names rather than rebuilding the spec machine.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .compiler import CompileResult

# Coarse buckets, mirroring the old SignalGroup. We only need build vs qc here (design/hygiene in
# the old system were warning-only); warnings stay in the warnings list, unclassified.
GROUP_OF = {
    "model_validity": "build",
    "mesh_assets": "build",
    "compile_runtime": "build",
    "real_overlap": "qc",
    "isolated_part": "qc",
    "disconnected_geometry": "qc",
    "articulation_origin": "qc",
    "coplanar_surface": "qc",
    "exact_contact_gap": "qc",
    "test_failure": "qc",
}


def classify_failure(name: str) -> tuple[str, str]:
    """Bucket a TestFailure `name` into (kind, group) from the old CompileSignal vocabulary.

    Order matters. `expect_*` are *intent* assertions, so they route by what they assert, not by
    keyword: a failed `expect_overlap` means parts that should touch don't — a proximity miss
    (exact_contact_gap), NOT an unintended collision (real_overlap). The one expect_* that's truly
    about the joint, `expect_joint_motion_axis`, goes to articulation_origin. Everything else is a
    QC check matched by keyword."""
    n = (name or "").lower()
    if n.startswith("expect_"):
        kind = "articulation_origin" if "motion_axis" in n else "exact_contact_gap"
    elif "coplanar" in n:
        kind = "coplanar_surface"
    elif "overlap" in n:
        kind = "real_overlap"
    elif "island" in n or "disconnected" in n:
        kind = "disconnected_geometry"
    elif "isolat" in n:
        kind = "isolated_part"
    elif "articulation" in n or "joint" in n or "motion_axis" in n:
        kind = "articulation_origin"
    elif "valid" in n:
        kind = "model_validity"
    elif "mesh" in n:
        kind = "mesh_assets"
    else:
        kind = "test_failure"
    return kind, GROUP_OF[kind]


def classify_error(error: str) -> tuple[str, str]:
    """Bucket a compile-time exception string ('ExcType: msg'). A ValidationError is the model
    being structurally invalid; anything else is a runtime build error."""
    kind = "model_validity" if (error or "").startswith("ValidationError") else "compile_runtime"
    return kind, GROUP_OF[kind]


# Warning sub-kinds. articraft carried these as structured CompileSignals (coplanar w/ max_risk,
# overlap sensors, deprecated-API, scale/outlier); this port reconstructs (kind, group) from the
# stable warning *text* the SDK emits, so warnings get the same `[group/kind]` tag as failures
# instead of riding through as raw prose. Matched by substring against the warn() strings in
# sdk/_core/v0/_testing. The "...allowed by justification" warnings are allowances, not problems —
# they route to Notes, not Warnings (see classify_warning -> "allowance").
def classify_warning(text: str) -> tuple[str, str]:
    t = (text or "").lower()
    if "allowed by justification" in t:  # emitted by the QC checks when an allow_*() silenced a hit
        return "allowance", "design"
    if "deprecated" in t:
        return "deprecated_test_api", "hygiene"
    if "coplanar" in t:
        return "coplanar_surface", "qc"
    if "overlaps detected" in t:
        return "overlap_warning", "qc"
    if "isolated parts detected" in t:
        return "isolated_part", "qc"
    if "disconnected" in t or "island" in t:
        return "disconnected_geometry", "qc"
    if "articulation-origin" in t or "articulation origin" in t:
        return "articulation_origin", "qc"
    return "warning", "design"


_RISK_RANK = {"low": 0, "medium": 1, "high": 2}


def _max_risk(text: str) -> str | None:
    """Coplanar warnings embed a `risk=<low|medium|high>` per finding; surface the highest so the
    model sees articraft's coplanar-vs-coplanar_hint severity split without rebuilding the signal."""
    risks = [r.lower() for r in re.findall(r"risk=(\w+)", text or "")]
    if not risks:
        # fall back to the headline wording when no per-finding risk token is present
        return "low" if "low-confidence" in (text or "").lower() else None
    return max(risks, key=lambda r: _RISK_RANK.get(r, 0))


def _warning_tag(text: str) -> str:
    kind, group = classify_warning(text)
    if kind == "coplanar_surface" and (risk := _max_risk(text)):
        return f"[{group}/{kind} max_risk={risk}]"
    return f"[{group}/{kind}]"


def source_of(kind: str) -> str:
    """#5 — which subsystem owns the failure: an SDK-standard QC check vs the model's own bespoke
    `ctx.check`/`ctx.fail`. (The third value, "build", is set directly on the compile-error path,
    where the model raised before geometry built — that's why source isn't pure-derivable from kind:
    model_validity is "build" when raised but "sdk_qc" when `check_model_valid` fails.)"""
    return "authored" if kind == "test_failure" else "sdk_qc"


def _kind_of(fa: dict) -> str:
    return fa.get("kind") or classify_failure(fa.get("name", ""))[0]


def _source_of(fa: dict) -> str:
    return fa.get("source") or source_of(_kind_of(fa))


# #2 — targeted hints for known compile-error fingerprints (needle in lowercased error text -> fix).
# Kept to the one that isn't already self-explanatory in the SDK's own message; extend as needed.
ERROR_HINTS = (
    (
        "no module named 'sdk.",
        "Hint: import authoring helpers from top-level `sdk` "
        "(e.g. `from sdk import Box, Origin, TestContext`), not guessed submodules.",
    ),
    (
        "exactly one root part",
        "Hint: this is a part-tree error, not a geometry one. Connect the extra root parts "
        "with an articulation or fixed mount so the object has a single root.",
    ),
)

# #1 — one-line next-step per failure kind. Grounded in helpers that ACTUALLY exist in this SDK:
# allow_overlap/allow_isolated_part, the expect_* checks, and probe_model (ctx.part_world_aabb /
# ctx.part_world_position). No invented `*_report` helpers from the old repo.
RESPONSE_RULES = {
    "compile_runtime": "Fix the runtime error first — geometry repair is blocked until the script runs cleanly.",
    "model_validity": "Structural model-definition error, not a placement issue. Read the validation detail before editing geometry.",
    "mesh_assets": "Missing or unresolved mesh assets. Fix the asset names/paths before tuning geometry or checks.",
    "real_overlap": "Real 3D overlap: fix it by editing geometry/pose, or if intentional add a scoped `allow_overlap(a, b, reason=...)`. Use `probe_model` (e.g. `ctx.part_world_aabb(part)`) if the cause isn't obvious.",
    "exact_contact_gap": "This is a gap, not an overlap — parts that should touch don't. Confirm you're testing the right pair, then move geometry/mounts to close it; don't just loosen the tolerance.",
    "isolated_part": "A floating/disconnected part. Connect it with an articulation or fixed mount, or `allow_isolated_part(part, reason=...)` if it's intentionally separate.",
    "disconnected_geometry": "Disconnected geometry islands inside one part — usually a real modeling bug. Inspect that part's visuals.",
    "articulation_origin": "The joint origin/axis sits far from its geometry. Recheck the articulation's origin and axis.",
    "test_failure": "A custom check failed. Classify whether it's a local bug, a wrong representation, or a stale check before patching.",
}

# Order the next-steps block: build blockers first, then QC geometry, then the catch-all.
_RULE_ORDER = (
    "compile_runtime",
    "model_validity",
    "mesh_assets",
    "real_overlap",
    "exact_contact_gap",
    "disconnected_geometry",
    "isolated_part",
    "articulation_origin",
    "test_failure",
)


def _hints_for(text: str) -> list[str]:
    low = (text or "").lower().replace('"', "'")
    return [hint for needle, hint in ERROR_HINTS if needle in low]


def format_feedback(result: "CompileResult") -> str:
    if result.error:
        kind, _ = classify_error(result.error)
        msg = f"COMPILE FAILED [build/{kind}]: {result.error}"
        if result.traceback:
            msg += f"\n\nTraceback:\n{result.traceback.strip()[-2000:]}"
        steps = _hints_for(f"{result.error} {result.traceback or ''}")
        if RESPONSE_RULES.get(kind):
            steps.append(RESPONSE_RULES[kind])
        if steps:
            msg += "\n\nNext steps:\n" + "\n".join(f"  - {s}" for s in steps)
        return msg

    lines: list[str] = []
    if result.failures:
        kinds = Counter(_kind_of(fa) for fa in result.failures)
        summary = ", ".join(f"{k}×{c}" for k, c in kinds.most_common())
        lines.append(f"COMPILED, but tests FAILED ({summary}):")
        for fa in result.failures:
            lines.append(
                f"  [{_source_of(fa)}/{_kind_of(fa)}] {fa.get('name', '?')}: {fa.get('details', '')}"
            )
        rules = [RESPONSE_RULES[k] for k in _RULE_ORDER if k in kinds and k in RESPONSE_RULES]
        if rules:
            lines.append("Next steps:")
            lines.extend(f"  - {r}" for r in rules)
    elif result.passed:
        lines.append("COMPILE OK: model compiled and all tests passed.")
    else:
        lines.append("COMPILE OK (no tests passed/failed reported).")

    # Warnings get the same `[group/kind]` tag as failures; "allowed by justification" warnings are
    # allowances and move to Notes instead. Notes also echoes the report's explicit allow_*() calls
    # (allowances / allowed_isolated_parts) so the model sees what it deliberately silenced.
    warn_lines, note_lines = [], []
    for w in result.warnings or ():
        (note_lines if classify_warning(w)[0] == "allowance" else warn_lines).append(w)
    if warn_lines:
        lines.append("Warnings:")
        lines.extend(f"  {_warning_tag(w)} {w.replace(chr(10), chr(10) + '    ')}" for w in warn_lines)

    notes = list(note_lines) + list(getattr(result, "allowances", None) or []) + list(
        getattr(result, "allowed_isolated_parts", None) or []
    )
    if notes:
        lines.append("Notes:")
        lines.extend(f"  - {n}" for n in notes)
    return "\n".join(lines)


def failure_signature(result: "CompileResult") -> str | None:
    """A stable fingerprint of *what* failed, for the harness/Workspace to detect a repeated
    failure across compiles (articraft's dedupe_key role). None when there's nothing blocking."""
    if result.error:
        return "error:" + classify_error(result.error)[0]
    if result.failures:
        return "fail:" + ";".join(
            sorted(f"{_kind_of(fa)}:{fa.get('name', '')}" for fa in result.failures)
        )
    return None


def repeated_failure_note(streak: int) -> str | None:
    """articraft's streak escalation, stateless: caller passes how many compiles in a row hit the same
    signature. This port has no in-band streak counter otherwise (the harness hard-stops via stall)."""
    if streak >= 3:
        return (
            f"This is the same failure {streak} compiles in a row. Another small tweak is unlikely "
            "to help — use `probe_model` to inspect the actual geometry/pose before editing again."
        )
    if streak == 2:
        return "This failure matches the previous compile attempt."
    return None


def _demo() -> None:
    assert classify_failure("fail_if_parts_overlap_in_sampled_poses") == ("real_overlap", "qc")
    assert classify_failure("fail_if_articulation_overlaps") == ("real_overlap", "qc")
    assert classify_failure("fail_if_articulation_origin_far_from_geometry") == (
        "articulation_origin",
        "qc",
    )
    assert classify_failure("fail_if_isolated_parts") == ("isolated_part", "qc")
    assert classify_failure("fail_if_part_contains_disconnected_geometry_islands") == (
        "disconnected_geometry",
        "qc",
    )
    assert classify_failure("warn_if_coplanar_surfaces") == ("coplanar_surface", "qc")
    assert classify_failure("expect_overlap") == (
        "exact_contact_gap",
        "qc",
    )  # failed "should touch" = gap, not collision
    assert classify_failure("expect_joint_motion_axis") == (
        "articulation_origin",
        "qc",
    )  # the joint-flavored expect_
    assert classify_failure("check_model_valid") == ("model_validity", "build")
    assert classify_failure("check_mesh_assets_ready") == ("mesh_assets", "build")
    assert classify_failure("my_custom_thing") == ("test_failure", "qc")
    assert classify_error("ValidationError: bad") == ("model_validity", "build")
    assert classify_error("ZeroDivisionError: x") == ("compile_runtime", "build")
    assert source_of("real_overlap") == "sdk_qc"
    assert source_of("test_failure") == "authored"

    from types import SimpleNamespace

    def res(**kw):
        return SimpleNamespace(
            **{
                "error": None,
                "traceback": None,
                "failures": [],
                "passed": False,
                "warnings": [],
                **kw,
            }
        )

    # #2: import error gets the sdk hint + the kind's rule, tagged build source.
    err = format_feedback(res(error="ModuleNotFoundError: No module named 'sdk.testing'"))
    assert "[build/compile_runtime]" in err
    assert "top-level `sdk`" in err and "Fix the runtime error first" in err
    # #1 + #5: failures get per-kind next steps + source tags; build-blocker ordered before qc.
    fb = format_feedback(
        res(
            failures=[
                {
                    "name": "fail_if_parts_overlap_in_current_pose",
                    "details": "x",
                    "kind": "real_overlap",
                    "source": "sdk_qc",
                },
                {
                    "name": "body_exists",
                    "details": "y",
                    "kind": "test_failure",
                    "source": "authored",
                },
            ]
        )
    )
    assert "[sdk_qc/real_overlap]" in fb and "[authored/test_failure]" in fb
    assert "Next steps:" in fb
    assert fb.index("Real 3D overlap") < fb.index(
        "custom check failed"
    )  # qc real_overlap before catch-all

    # warning sub-kinds get structured tags; coplanar carries max_risk; deprecated -> hygiene
    assert classify_warning("DEPRECATED: foo uses legacy semantics") == ("deprecated_test_api", "hygiene")
    assert classify_warning("Coplanar or nearly coplanar surfaces detected\nrisk=high ...") == ("coplanar_surface", "qc")
    assert classify_warning("Overlaps detected (overlap_tol=...)") == ("overlap_warning", "qc")
    assert classify_warning("Overlaps detected but allowed by justification: 2 overlaps") == ("allowance", "design")
    assert _max_risk("risk=low x risk=high y") == "high"
    assert _max_risk("Low-confidence coplanar-surface hints detected") == "low"
    wfb = format_feedback(
        res(
            passed=True,
            warnings=[
                "Coplanar or nearly coplanar surfaces detected\nrisk=medium pair=('a','b')",
                "DEPRECATED: warn_if_overlaps(...) uses legacy AABB-envelope semantics.",
                "Overlaps detected but allowed by justification: 1 overlaps.",
            ],
            allowances=["allow_overlap('a','b'): hinge clearance"],
        )
    )
    assert "[qc/coplanar_surface max_risk=medium]" in wfb, wfb
    assert "[hygiene/deprecated_test_api]" in wfb, wfb
    assert "Notes:" in wfb and "hinge clearance" in wfb, wfb
    assert "allowed by justification" in wfb[wfb.index("Notes:") :], wfb  # routed to notes, not warnings

    # streak fingerprint + escalation
    s1 = failure_signature(res(failures=[{"name": "x", "kind": "real_overlap"}]))
    assert s1 == failure_signature(res(failures=[{"name": "x", "kind": "real_overlap"}]))  # stable
    assert s1 != failure_signature(res(failures=[{"name": "y", "kind": "real_overlap"}]))
    assert failure_signature(res(passed=True)) is None
    assert repeated_failure_note(1) is None
    assert "matches the previous" in repeated_failure_note(2)
    assert "3 compiles in a row" in repeated_failure_note(3)
    print("ok")


if __name__ == "__main__":
    _demo()
