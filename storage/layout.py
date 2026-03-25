from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class StorageLayout:
    root: Path

    @property
    def data_root(self) -> Path:
        return self.root / "data"

    @property
    def supercategories_path(self) -> Path:
        return self.data_root / "supercategories.json"

    @property
    def categories_root(self) -> Path:
        return self.data_root / "categories"

    @property
    def system_prompts_root(self) -> Path:
        return self.data_root / "system_prompts"

    @property
    def batch_specs_root(self) -> Path:
        return self.data_root / "batch_specs"

    @property
    def records_root(self) -> Path:
        return self.data_root / "records"

    @property
    def local_root(self) -> Path:
        return self.data_root / "local"

    @property
    def cache_root(self) -> Path:
        return self.data_root / "cache"

    @property
    def manifests_root(self) -> Path:
        return self.cache_root / "manifests"

    @property
    def trajectory_unroll_root(self) -> Path:
        return self.cache_root / "trajectory_unroll"

    @property
    def trajectory_unroll_records_root(self) -> Path:
        return self.trajectory_unroll_root / "records"

    @property
    def trajectory_unroll_staging_root(self) -> Path:
        return self.trajectory_unroll_root / "staging"

    @property
    def record_materializations_root(self) -> Path:
        return self.cache_root / "record_materialization"

    @property
    def runs_root(self) -> Path:
        return self.cache_root / "runs"

    def category_dir(self, category_slug: str) -> Path:
        return self.categories_root / category_slug

    def category_metadata_path(self, category_slug: str) -> Path:
        return self.category_dir(category_slug) / "category.json"

    def system_prompt_path(self, prompt_sha256: str) -> Path:
        return self.system_prompts_root / f"{prompt_sha256}.txt"

    def prompt_batches_dir(self, category_slug: str) -> Path:
        return self.category_dir(category_slug) / "prompt_batches"

    def prompt_batch_path(self, category_slug: str, batch_id: str) -> Path:
        return self.prompt_batches_dir(category_slug) / f"{batch_id}.txt"

    def batch_spec_path(self, batch_id: str) -> Path:
        return self.batch_specs_root / f"{batch_id}.csv"

    def local_workbench_path(self) -> Path:
        return self.local_root / "workbench.json"

    def dataset_manifest_path(self) -> Path:
        return self.manifests_root / "dataset.json"

    def search_index_path(self) -> Path:
        return self.cache_root / "search_index.json"

    def record_dir(self, record_id: str) -> Path:
        return self.records_root / record_id

    def record_metadata_path(self, record_id: str) -> Path:
        return self.record_dir(record_id) / "record.json"

    def record_dataset_entry_path(self, record_id: str) -> Path:
        return self.record_dir(record_id) / "dataset_entry.json"

    def record_inputs_dir(self, record_id: str) -> Path:
        return self.record_dir(record_id) / "inputs"

    def record_traces_dir(self, record_id: str) -> Path:
        return self.record_dir(record_id) / "traces"

    def record_trajectory_unroll_path(self, record_id: str) -> Path:
        return self.trajectory_unroll_records_root / record_id / "trajectory.jsonl"

    def record_assets_dir(self, record_id: str) -> Path:
        return self.record_dir(record_id) / "assets"

    def record_asset_meshes_dir(self, record_id: str) -> Path:
        return self.record_assets_dir(record_id) / "meshes"

    def record_asset_glb_dir(self, record_id: str) -> Path:
        return self.record_assets_dir(record_id) / "glb"

    def record_asset_viewer_dir(self, record_id: str) -> Path:
        return self.record_assets_dir(record_id) / "viewer"

    def record_materialization_dir(self, record_id: str) -> Path:
        return self.record_materializations_root / record_id

    def record_materialization_urdf_path(self, record_id: str) -> Path:
        return self.record_materialization_dir(record_id) / "model.urdf"

    def record_materialization_compile_report_path(self, record_id: str) -> Path:
        return self.record_materialization_dir(record_id) / "compile_report.json"

    def record_materialization_assets_dir(self, record_id: str) -> Path:
        return self.record_materialization_dir(record_id) / "assets"

    def record_materialization_asset_meshes_dir(self, record_id: str) -> Path:
        return self.record_materialization_assets_dir(record_id) / "meshes"

    def record_materialization_asset_glb_dir(self, record_id: str) -> Path:
        return self.record_materialization_assets_dir(record_id) / "glb"

    def record_materialization_asset_viewer_dir(self, record_id: str) -> Path:
        return self.record_materialization_assets_dir(record_id) / "viewer"

    def run_dir(self, run_id: str) -> Path:
        return self.runs_root / run_id

    def staging_trajectory_unroll_path(self, run_id: str, record_id: str) -> Path:
        return self.trajectory_unroll_staging_root / run_id / record_id / "trajectory.jsonl"

    def run_metadata_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "run.json"

    def run_results_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "results.jsonl"

    def run_staging_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "staging"

    def run_failures_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "failures"

    def run_state_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "state"

    def run_row_state_path(self, run_id: str, row_id: str) -> Path:
        return self.run_state_dir(run_id) / f"{row_id}.json"

    def run_allocations_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "allocations.json"

    def ensure_base_dirs(self) -> None:
        for path in (
            self.categories_root,
            self.system_prompts_root,
            self.batch_specs_root,
            self.records_root,
            self.local_root,
            self.manifests_root,
            self.trajectory_unroll_records_root,
            self.trajectory_unroll_staging_root,
            self.record_materializations_root,
            self.runs_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
