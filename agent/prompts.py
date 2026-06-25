"""Assemble the LLM-visible first-turn context: system prompt, SDK docs, runtime guidance.

Matches articraft's openai pathway:
- the system prompt is articraft's designer prompt verbatim (filename from the SDK profile; no docs inlined);
- the SDK docs ride in a SEPARATE first-turn user message (a small preloaded bundle, detailed
  docs reachable via read_file), reproducing articraft's `load_sdk_docs_reference`;
- the runtime guidance block is prepended to the user's prompt on the first turn.
No templating engine.
"""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

from sdk._profiles import get_sdk_profile

_AGENT_PACKAGE = "agent"  # the designer prompt is shipped as package data alongside this module

# articraft's openai-path first-turn runtime guidance (agent/tools/__init__._FIRST_TURN_RUNTIME_GUIDANCE_SHARED),
# prepended to the user's prompt on turn one.
RUNTIME_GUIDANCE = (
    "<runtime_task_guidance>\n"
    "- Read the current `model.py` before editing.\n"
    "- Start with a realism-first structure plan. Use one coherent scaffold when the real object needs layered bodies, hollow forms, mechanisms, or repeated features; otherwise make small focused edits.\n"
    "- Treat visual realism as part of the deliverable: make the object read clearly as the requested thing, with believable proportions, silhouette, colors/materials, and major visible surface treatment.\n"
    "- Run `compile_model` to check your latest revision.\n"
    "- If compile is clean and the model already satisfies the realism/mechanism brief, conclude.\n"
    "</runtime_task_guidance>"
)

# Each SDK doc (`sdk/_docs/<area>/NN_name.md`) is advertised to the model under a virtual
# `docs/sdk/<subtree>/<slug>.md` path. These strings are LLM-visible (they appear in the preloaded
# docs bundle and in the model's read_file calls) and must stay byte-identical to articraft's openai
# workspace — but the mapping is regular enough to derive instead of hand-listing one entry per doc.
_AREA_SUBTREE = {
    "common": "references",
    "base": "references/geometry",
    "cadquery": "references/cadquery",
}
# The handful of cadquery filenames articraft slugs irregularly (the index, and a pluralized name);
# everything else follows the rule in `_virtual_doc_path`.
_SLUG_OVERRIDES = {"35_cadquery": "overview", "39b_cadquery_free_function": "free-functions"}


def _virtual_doc_path(rel_path: Path) -> str | None:
    """Virtual `docs/sdk/...` path for an SDK doc, or None if its area isn't advertised."""
    subtree = _AREA_SUBTREE.get(rel_path.parent.name)
    if subtree is None:
        return None
    slug = _SLUG_OVERRIDES.get(rel_path.stem)
    if slug is None:
        body = re.sub(r"^\d+[a-z]?_", "", rel_path.stem)  # drop the ordering prefix
        if rel_path.parent.name == "cadquery":
            body = re.sub(r"^cadquery_", "", body)  # the cadquery subtree drops the redundant token
        slug = body.replace("_", "-")
    return f"docs/sdk/{subtree}/{slug}.md"

# articraft's workspace_docs._DEFAULT_PRELOAD_PATHS: the docs inlined into the first-turn user message.
# Everything else stays behind read_file(path="docs/sdk/...").
_PRELOAD_VIRTUAL_PATHS = (
    "docs/sdk/references/quickstart.md",
    "docs/sdk/references/probe-tooling.md",
    "docs/sdk/references/testing.md",
)


def doc_map(sdk_package: str = "sdk") -> dict[str, Path]:
    """All SDK docs readable via read_file, keyed by the virtual `docs/sdk/...` path the prompt
    advertises (mirrors articraft's virtual workspace). Detailed docs are read on demand."""
    profile = get_sdk_profile(sdk_package)
    root = files(profile.package_name)  # installed sdk package, not a repo-relative guess
    docs: dict[str, Path] = {}
    for rel_path in profile.docs_full:
        virtual = _virtual_doc_path(rel_path)
        if virtual is None:
            continue
        inner = rel_path.relative_to(profile.package_name).as_posix()  # strip leading "sdk/"
        resource = root.joinpath(inner)
        if resource.is_file():
            docs[virtual] = resource
    return docs


def build_system_prompt(sdk_package: str = "sdk") -> str:
    """The designer system prompt, verbatim. SDK docs are NOT inlined here — they ride in a
    separate first-turn user message (build_sdk_docs_context)."""
    name = get_sdk_profile(sdk_package).designer_prompt_name
    resource = files(_AGENT_PACKAGE).joinpath(name)
    if not resource.is_file():
        raise FileNotFoundError(
            f"designer system prompt {name!r} is missing from the installed `agent` package — "
            "check it ships as package data (pyproject [tool.hatch.build.targets.wheel])."
        )
    return resource.read_text(encoding="utf-8")


def build_sdk_docs_context(sdk_package: str = "sdk") -> str:
    """articraft's load_sdk_docs_reference: a small preloaded docs bundle delivered as a first-turn user
    message. Detailed docs live behind read_file, so this stays small."""
    docs = doc_map(sdk_package)
    parts = [
        "\n\n# Workspace Documentation (read-only)\n",
        "The virtual workspace exposes `model.py` as the editable artifact script and `docs/` "
        "as read-only SDK guidance.\n",
        "`docs/sdk/references/quickstart.md` is the preloaded SDK entrypoint and reference index.\n",
        "Use `read_file(path=...)` with these virtual paths when you need exact text.\n",
    ]
    for virtual_path in _PRELOAD_VIRTUAL_PATHS:
        body = docs[virtual_path].read_text(encoding="utf-8")
        parts.append(f"\n## {virtual_path}\n````markdown\n{body}\n````\n")
    return "".join(parts)
