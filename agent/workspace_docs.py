from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from sdk._profiles import get_sdk_profile

_FRONTMATTER_RE = re.compile(r"\A---\n(?P<frontmatter>.*?)\n---\n?(?P<body>.*)\Z", re.DOTALL)
_SDK_ROUTER_SOURCE = Path("agent/docs/sdk/README.md")
_SDK_ROUTER_VIRTUAL_PATH = "docs/sdk/README.md"
_MODEL_VIRTUAL_PATH = "model.py"


@dataclass(frozen=True)
class DocsRouterFrontmatter:
    name: str
    description: str
    always_load: bool
    default_reads: tuple[str, ...]
    writable_paths: tuple[str, ...]
    read_only_roots: tuple[str, ...]


@dataclass(frozen=True)
class VirtualWorkspaceFile:
    virtual_path: str
    disk_path: Path | None = None
    content: str | None = None

    def read_text(self) -> str:
        if self.content is not None:
            return self.content
        if self.disk_path is None:
            raise FileNotFoundError(f"No backing content for {self.virtual_path}")
        return self.disk_path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class DocsBundle:
    router: VirtualWorkspaceFile
    frontmatter: DocsRouterFrontmatter
    files_by_path: dict[str, VirtualWorkspaceFile]

    def read_text(self, virtual_path: str) -> str:
        return self.resolve(virtual_path).read_text()

    def resolve(self, virtual_path: str) -> VirtualWorkspaceFile:
        normalized = normalize_virtual_workspace_path(virtual_path)
        try:
            return self.files_by_path[normalized]
        except KeyError as exc:
            raise FileNotFoundError(f"Unknown virtual docs path: {normalized}") from exc

    def default_read_virtual_paths(self) -> tuple[str, ...]:
        return tuple(
            _resolve_sdk_docs_relative_path(path) for path in self.frontmatter.default_reads
        )


@dataclass(frozen=True)
class VirtualWorkspace:
    model_file_path: Path
    docs_bundle: DocsBundle

    def resolve(self, virtual_path: str) -> VirtualWorkspaceFile:
        normalized = normalize_virtual_workspace_path(virtual_path)
        if normalized == _MODEL_VIRTUAL_PATH:
            return VirtualWorkspaceFile(
                virtual_path=_MODEL_VIRTUAL_PATH,
                disk_path=self.model_file_path,
            )
        return self.docs_bundle.resolve(normalized)


def normalize_virtual_workspace_path(path: str) -> str:
    candidate = (path or "").strip().replace("\\", "/")
    if not candidate:
        raise ValueError("path must not be empty")
    if candidate.startswith("/"):
        raise ValueError("path must be a virtual workspace path, not an absolute path")
    parts = [part for part in candidate.split("/") if part not in {"", "."}]
    if not parts:
        raise ValueError("path must not be empty")
    if any(part == ".." for part in parts):
        raise ValueError("path must not contain '..'")
    return "/".join(parts)


def build_virtual_workspace(
    repo_root: Path,
    *,
    model_file_path: Path,
    sdk_package: str,
) -> VirtualWorkspace:
    return VirtualWorkspace(
        model_file_path=model_file_path,
        docs_bundle=load_sdk_docs_bundle(repo_root, sdk_package=sdk_package),
    )


def load_sdk_docs_reference(
    repo_root: Path,
    *,
    sdk_package: str = "sdk",
    docs_mode: str = "full",
) -> str:
    # Detailed docs now live behind `read_file(path=...)`, so the preloaded bundle stays small
    # regardless of the legacy docs_mode setting.
    del docs_mode
    bundle = load_sdk_docs_bundle(repo_root, sdk_package=sdk_package)
    preload_paths = (_SDK_ROUTER_VIRTUAL_PATH, *bundle.default_read_virtual_paths())

    parts = [
        "\n\n# Workspace Documentation (read-only)\n",
        "The virtual workspace exposes `model.py` as the editable artifact script and `docs/` "
        "as read-only SDK guidance.\n",
        "Use `read_file(path=...)` with these virtual paths when you need exact text.\n",
    ]
    for virtual_path in preload_paths:
        parts.append(f"\n## {virtual_path}\n````markdown\n{bundle.read_text(virtual_path)}\n````\n")
    return "".join(parts)


def load_sdk_docs_bundle(repo_root: Path, *, sdk_package: str) -> DocsBundle:
    router = _load_router_document(repo_root)
    files_by_path: dict[str, VirtualWorkspaceFile] = {
        router.router.virtual_path: router.router,
        **_build_sdk_reference_files(repo_root, sdk_package=sdk_package),
    }
    return DocsBundle(
        router=router.router,
        frontmatter=router.frontmatter,
        files_by_path=files_by_path,
    )


@dataclass(frozen=True)
class _LoadedRouter:
    router: VirtualWorkspaceFile
    frontmatter: DocsRouterFrontmatter


def _load_router_document(repo_root: Path) -> _LoadedRouter:
    path = repo_root / _SDK_ROUTER_SOURCE
    text = path.read_text(encoding="utf-8")
    frontmatter, _body = _parse_markdown_frontmatter(text, source=path)
    metadata = DocsRouterFrontmatter(
        name=str(frontmatter.get("name") or "").strip(),
        description=str(frontmatter.get("description") or "").strip(),
        always_load=bool(frontmatter.get("always_load", True)),
        default_reads=tuple(str(item).strip() for item in frontmatter.get("default_reads") or []),
        writable_paths=tuple(
            str(item).strip() for item in frontmatter.get("writable_paths") or [_MODEL_VIRTUAL_PATH]
        ),
        read_only_roots=tuple(
            str(item).strip() for item in frontmatter.get("read_only_roots") or ["docs/"]
        ),
    )
    if not metadata.name:
        raise ValueError(f"{path}: missing required frontmatter field 'name'")
    if not metadata.description:
        raise ValueError(f"{path}: missing required frontmatter field 'description'")
    return _LoadedRouter(
        router=VirtualWorkspaceFile(
            virtual_path=_SDK_ROUTER_VIRTUAL_PATH,
            disk_path=path,
        ),
        frontmatter=metadata,
    )


def _parse_markdown_frontmatter(text: str, *, source: Path) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{source}: expected YAML frontmatter delimited by ---")
    frontmatter = yaml.safe_load(match.group("frontmatter")) or {}
    if not isinstance(frontmatter, dict):
        raise ValueError(f"{source}: frontmatter must decode to a mapping")
    body = match.group("body")
    return frontmatter, body


def _build_sdk_reference_files(
    repo_root: Path,
    *,
    sdk_package: str,
) -> dict[str, VirtualWorkspaceFile]:
    profile = get_sdk_profile(sdk_package)
    files: dict[str, VirtualWorkspaceFile] = {
        "docs/sdk/references/runtime.md": VirtualWorkspaceFile(
            virtual_path="docs/sdk/references/runtime.md",
            content=_build_runtime_doc(sdk_package=sdk_package),
        ),
        "docs/sdk/references/native-vs-cadquery.md": VirtualWorkspaceFile(
            virtual_path="docs/sdk/references/native-vs-cadquery.md",
            content=_build_native_vs_cadquery_doc(sdk_package=sdk_package),
        ),
    }

    for rel_path in profile.docs_full:
        rel_str = rel_path.as_posix()
        virtual_suffix = _DOC_PATH_ALIASES.get(rel_str)
        if virtual_suffix is None:
            continue
        files[f"docs/sdk/{virtual_suffix}"] = VirtualWorkspaceFile(
            virtual_path=f"docs/sdk/{virtual_suffix}",
            disk_path=repo_root / rel_path,
        )
    return files


def _build_runtime_doc(*, sdk_package: str) -> str:
    if sdk_package == "sdk_hybrid":
        return (
            "# Runtime\n\n"
            "- Import from `sdk_hybrid` in `model.py`.\n"
            "- This runtime includes the articulated-object/test/export stack plus CadQuery-backed "
            "geometry helpers.\n"
            "- Use native Articraft abstractions when they clearly express the object.\n"
            "- Use CadQuery when lower-level geometry control or shape construction warrants it.\n"
            "- `section_loft(...)`, `repair_loft(...)`, and `partition_shell(...)` are unavailable "
            "in this runtime.\n"
            "- Only `model.py` is writable. All `docs/` paths are read-only.\n"
        )
    return (
        "# Runtime\n\n"
        "- Import from `sdk` in `model.py`.\n"
        "- This runtime includes both the Articraft-native geometry/tooling surface and the "
        "CadQuery-backed geometry helpers.\n"
        "- Prefer native Articraft abstractions first, then use CadQuery when lower-level "
        "shape construction or construction history is the clearer fit.\n"
        "- `section_loft(...)`, `repair_loft(...)`, and `partition_shell(...)` remain "
        "available alongside the CadQuery path.\n"
        "- Only `model.py` is writable. All `docs/` paths are read-only.\n"
    )


def _build_native_vs_cadquery_doc(*, sdk_package: str) -> str:
    if sdk_package == "sdk_hybrid":
        return (
            "# Native vs CadQuery\n\n"
            "- Default to Articraft-native abstractions for articulated structure, placements, "
            "tests, and straightforward geometry.\n"
            "- Reach for CadQuery when shells, local cut geometry, smooth transitions, or precise "
            "construction history are easier to express at the lower level.\n"
            "- Mixing native Articraft and CadQuery-backed geometry in one artifact is allowed "
            "when it produces a clearer, more realistic model.\n"
            "- Keep units in meters by the time geometry reaches Articraft export helpers.\n"
        )
    return (
        "# Native vs CadQuery\n\n"
        "- Default to Articraft-native abstractions for articulated structure, placements, "
        "tests, and straightforward geometry.\n"
        "- Reach for CadQuery when shells, local cut geometry, smooth transitions, precise "
        "construction history, or richer low-level shape composition make the model clearer.\n"
        "- Mixing native Articraft geometry helpers with CadQuery-backed meshes in one artifact "
        "is allowed when it produces a more realistic result.\n"
        "- Keep units in meters by the time geometry reaches Articraft export helpers.\n"
    )


def _resolve_sdk_docs_relative_path(path: str) -> str:
    normalized = normalize_virtual_workspace_path(path)
    if normalized.startswith("docs/"):
        return normalized
    if normalized == _MODEL_VIRTUAL_PATH:
        return normalized
    return f"docs/sdk/{normalized}"


_DOC_PATH_ALIASES = {
    "sdk/_docs/common/00_quickstart.md": "references/quickstart.md",
    "sdk/_docs/common/10_errors.md": "references/errors.md",
    "sdk/_docs/common/20_core_types.md": "references/core-types.md",
    "sdk/_docs/common/30_articulated_object.md": "references/articulated-object.md",
    "sdk/_docs/common/50_placement.md": "references/placement.md",
    "sdk/_docs/common/70_probe_tooling.md": "references/probe-tooling.md",
    "sdk/_docs/common/80_testing.md": "references/testing.md",
    "sdk/_docs/base/40_mesh_geometry.md": "references/geometry/mesh-geometry.md",
    "sdk/_docs/base/45_wires.md": "references/geometry/wires.md",
    "sdk/_docs/base/46_section_lofts.md": "references/geometry/section-lofts.md",
    "sdk/_docs/cadquery/35_cadquery.md": "references/cadquery/overview.md",
    "sdk/_docs/cadquery/36_cadquery_primer.md": "references/cadquery/primer.md",
    "sdk/_docs/cadquery/37_cadquery_workplane.md": "references/cadquery/workplane.md",
    "sdk/_docs/cadquery/38_cadquery_sketch.md": "references/cadquery/sketch.md",
    "sdk/_docs/cadquery/39_cadquery_assembly.md": "references/cadquery/assembly.md",
    "sdk/_docs/cadquery/39b_cadquery_free_function.md": "references/cadquery/free-functions.md",
    "sdk/_docs/cadquery/39c_cadquery_api_ref.md": "references/cadquery/api-ref.md",
}
