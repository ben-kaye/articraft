from __future__ import annotations

from storage.materialize import infer_materialization_status
from storage.repo import StorageRepo


def test_infer_materialization_status_marks_primitive_only_success_as_available(
    tmp_path,
) -> None:
    repo = StorageRepo(tmp_path)
    repo.ensure_layout()

    record_id = "rec_primitive"
    record_dir = repo.layout.record_dir(record_id)
    record_dir.mkdir(parents=True, exist_ok=True)
    (record_dir / "model.urdf").write_text(
        "<robot name='primitive'><link name='base'><visual><geometry><box size='1 1 1'/></geometry></visual></link></robot>",
        encoding="utf-8",
    )

    status = infer_materialization_status(repo, record_id)

    assert status == "available"


def test_infer_materialization_status_keeps_mesh_backed_urdf_missing_without_assets(
    tmp_path,
) -> None:
    repo = StorageRepo(tmp_path)
    repo.ensure_layout()

    record_id = "rec_mesh"
    record_dir = repo.layout.record_dir(record_id)
    record_dir.mkdir(parents=True, exist_ok=True)
    (record_dir / "model.urdf").write_text(
        "<robot name='mesh'><link name='base'><visual><geometry><mesh filename='assets/meshes/base.obj'/></geometry></visual></link></robot>",
        encoding="utf-8",
    )

    status = infer_materialization_status(repo, record_id)

    assert status == "missing"
