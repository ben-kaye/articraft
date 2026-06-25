"""Reduce a run's trace into queryable analytics. Pure function over the trace list that
harness.py already persists (trace.json.gz) — no new instrumentation, backfills old records.

  uv run python -m agent.analytics                 # table over all records
  uv run python -m agent.analytics <record_id>     # one record, full JSON
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .feedback import classify_failure, source_of


def reduce_trace(trace: list[dict]) -> dict[str, Any]:
    """trace -> {turns, tool_counts, compiles, turns_to_pass, passed,
    viewed_examples, viewed_docs, failure_signatures, edit_turns, error}."""
    turns = [t for t in trace if "turn" in t and "tool_calls" in t]
    tool_counts: Counter[str] = Counter()
    viewed_examples: list[str] = []
    viewed_docs: list[str] = []
    failures: Counter[str] = Counter()
    failure_kinds: Counter[str] = Counter()
    failure_sources: Counter[str] = Counter()
    compiles: list[bool] = []  # passed flag per compile call, in order
    turns_to_pass: int | None = None
    edit_turns = 0
    EDIT = {"write_file", "str_replace"}

    for t in turns:
        names = [c["name"] for c in t["tool_calls"]]
        tool_counts.update(names)
        if any(n in EDIT for n in names):
            edit_turns += 1
        for c in t["tool_calls"]:
            for vid in c.get("viewed_ids", []):
                (viewed_examples if c["name"] == "find_examples" else viewed_docs).append(vid)
            comp = c.get("compile")
            if comp is not None:
                compiles.append(bool(comp["passed"]))
                if comp["passed"] and turns_to_pass is None:
                    turns_to_pass = t["turn"]
                for f in comp.get("failures") or []:
                    # failures are dicts; key by name/id when present, else the stringified dict.
                    failures[str(f.get("name") or f.get("id") or f)] += 1
                    # kind/source ride the dict on new traces; derive from name to backfill old ones.
                    kind = f.get("kind") or classify_failure(f.get("name", ""))[0]
                    failure_kinds[kind] += 1
                    failure_sources[f.get("source") or source_of(kind)] += 1

    return {
        "turns": len(turns),
        "tool_counts": dict(tool_counts),
        "compiles": len(compiles),
        "first_pass_compile_idx": compiles.index(True) + 1 if True in compiles else None,
        "turns_to_pass": turns_to_pass,
        "passed": bool(compiles and compiles[-1]),
        "edit_turns": edit_turns,
        "viewed_examples": viewed_examples,  # find_examples hits the model actually saw
        "viewed_docs": viewed_docs,  # read_file doc paths (excludes model.py reads? no — incl.)
        "failure_signatures": dict(failures),
        "failure_kinds": dict(failure_kinds),
        "failure_sources": dict(failure_sources),
        "error": next((t["error"] for t in trace if "error" in t), None),
    }


_EDIT = {"write_file", "str_replace"}
_PROBE = {"probe_model", "probe_target"}


def meta_turns(trace: list[dict]) -> list[dict]:
    """Segment raw turns into meta-turns that each END with a model.py edit. A meta-turn is
    one "inspect the current state, then commit an edit" unit: the read/probe turns that
    reason about the current geometry, closed by the write_file/str_replace that acts on it.

      {index, raw_turns:[int], edit_turn:int|None, geometry_turn:int|None,
       passed:bool, probes:[{turn,name,args,result}]}

    A meta-turn closes on each edit turn (edit_turn = that closing turn); probe/read turns
    after the final edit form a trailing meta-turn (edit_turn=None). geometry_turn is the
    last compile-ok snapshot in the span — the state the span's probes ran against, what the
    viewer renders; passed is the span's last compile.passed.
    """
    turns = [t for t in trace if "turn" in t and "tool_calls" in t]
    metas: list[dict] = []
    cur = {"raw_turns": [], "edit_turn": None, "geometry_turn": None, "passed": False, "probes": []}

    def close() -> None:
        cur["index"] = len(metas)
        metas.append(cur)

    for t in turns:
        names = [c["name"] for c in t["tool_calls"]]
        cur["raw_turns"].append(t["turn"])
        for c in t["tool_calls"]:
            comp = c.get("compile")
            if comp is not None:
                if comp.get("ok"):
                    cur["geometry_turn"] = t["turn"]
                cur["passed"] = bool(comp.get("passed"))
            if c["name"] in _PROBE:
                cur["probes"].append(
                    {
                        "turn": t["turn"],
                        "name": c["name"],
                        "args": c.get("args", {}),
                        "result": c.get("result", ""),
                    }
                )
        if any(n in _EDIT for n in names):  # this edit closes the meta-turn
            cur["edit_turn"] = t["turn"]
            close()
            cur = {"raw_turns": [], "edit_turn": None, "geometry_turn": None, "passed": False, "probes": []}
    if cur["raw_turns"]:  # trailing probes/reads after the last edit
        close()
    return metas


def _demo() -> None:
    trace = [
        {
            "turn": 1,
            "tool_calls": [
                {"name": "find_examples", "viewed_ids": ["rec_abc", "examples/box.md"]},
                {"name": "read_file", "viewed_ids": ["cadquery_workplane.md"]},
            ],
        },
        {
            "turn": 2,
            "tool_calls": [
                {"name": "write_file"},
                {
                    "name": "compile",
                    "compile": {
                        "passed": False,
                        "failures": [{"name": "fail_if_parts_overlap_in_sampled_poses"}],
                    },
                },
            ],
        },
        {
            "turn": 3,
            "tool_calls": [
                {"name": "str_replace"},
                {"name": "compile", "compile": {"passed": True, "failures": []}},
            ],
        },
    ]
    m = reduce_trace(trace)
    assert m["turns"] == 3
    assert m["tool_counts"] == {
        "find_examples": 1,
        "read_file": 1,
        "write_file": 1,
        "str_replace": 1,
        "compile": 2,
    }
    assert m["compiles"] == 2
    assert m["turns_to_pass"] == 3
    assert m["first_pass_compile_idx"] == 2
    assert m["passed"] is True
    assert m["edit_turns"] == 2
    assert m["viewed_examples"] == ["rec_abc", "examples/box.md"]
    assert m["viewed_docs"] == ["cadquery_workplane.md"]
    assert m["failure_signatures"] == {"fail_if_parts_overlap_in_sampled_poses": 1}
    assert m["failure_kinds"] == {"real_overlap": 1}  # backfilled by classify_failure
    assert m["failure_sources"] == {"sdk_qc": 1}  # SDK-standard check, not authored
    # empty / error traces don't explode
    assert reduce_trace([])["passed"] is False
    assert reduce_trace([{"turn": 1, "error": "Boom"}])["error"] == "Boom"

    # meta_turns: each span ENDS with its edit; the probes leading up to an edit collapse
    # into that edit's meta-turn. A trailing probe with no following edit is its own span.
    mt_trace = [
        {"turn": 1, "tool_calls": [{"name": "probe_target", "args": {}, "result": "summary"}]},
        {
            "turn": 2,
            "tool_calls": [
                {"name": "write_file"},
                {"name": "compile", "compile": {"ok": True, "passed": False}},
            ],
        },
        {"turn": 3, "tool_calls": [{"name": "probe_target", "args": {"code": "x"}, "result": "r"}]},
        {"turn": 4, "tool_calls": [{"name": "probe_model", "args": {"code": "y"}, "result": "r2"}]},
        {
            "turn": 5,
            "tool_calls": [
                {"name": "str_replace"},
                {"name": "compile", "compile": {"ok": True, "passed": True}},
            ],
        },
        {"turn": 6, "tool_calls": [{"name": "probe_model", "args": {}, "result": "r3"}]},
    ]
    mts = meta_turns(mt_trace)
    assert [m["index"] for m in mts] == [0, 1, 2]
    # span 0 = [probe t1, edit t2]: the opening probe collapses into the first edit's span.
    assert mts[0]["raw_turns"] == [1, 2] and mts[0]["edit_turn"] == 2
    assert mts[0]["geometry_turn"] == 2 and mts[0]["passed"] is False
    assert [p["turn"] for p in mts[0]["probes"]] == [1]
    # span 1 = [probe t3, probe t4, edit t5]: probes reasoning toward edit t5.
    assert mts[1]["raw_turns"] == [3, 4, 5] and mts[1]["edit_turn"] == 5
    assert mts[1]["geometry_turn"] == 5 and mts[1]["passed"] is True
    assert [p["turn"] for p in mts[1]["probes"]] == [3, 4]
    # span 2 = trailing probe, no closing edit.
    assert mts[2]["raw_turns"] == [6] and mts[2]["edit_turn"] is None
    assert meta_turns([]) == []
    print("ok")


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        _demo()
        sys.exit()

    from pathlib import Path

    from storage.db import Repo
    from storage.records import RecordStore

    store = RecordStore(Repo(Path(".")))
    if len(sys.argv) > 1:
        print(json.dumps(reduce_trace(store.load_trace(sys.argv[1])), indent=2))
    else:
        for rid in store.list_ids():
            try:
                m = reduce_trace(store.load_trace(rid))
            except FileNotFoundError:
                continue
            print(
                f"{rid}  pass={m['passed']!s:5} turns={m['turns']:>2} "
                f"ttp={m['turns_to_pass']} edits={m['edit_turns']} "
                f"ex={len(m['viewed_examples'])} tools={m['tool_counts']}"
            )
