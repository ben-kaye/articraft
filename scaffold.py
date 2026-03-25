from __future__ import annotations

# User code should import every SDK/stdlib symbol it uses instead of relying on
# hidden scaffold imports.
# >>> USER_CODE_START
from sdk import ArticulatedObject, AssetContext, TestContext, TestReport

ASSETS = AssetContext.from_script(__file__)


def build_object_model() -> ArticulatedObject:
    model = ArticulatedObject(name="draft_model", assets=ASSETS)
    return model


def run_tests() -> TestReport:
    ctx = TestContext(object_model, asset_root=ASSETS.asset_root)
    ctx.check_model_valid()
    ctx.check_mesh_files_exist()

    # Preferred default QC stack:
    # 1) likely-failure broad-part floating check for isolated parts
    ctx.check_no_isolated_parts()
    # 2) noisier warning-tier sensor for same-part disconnected geometry islands
    ctx.warn_if_part_geometry_disconnected()
    # 3) likely-failure rest-pose part-to-part overlap backstop for broad interpenetration
    # Investigate all three. Warning-tier signals are not free passes.
    # If a seated or nested fit is intentional, justify it with `ctx.allow_overlap(...)`.
    ctx.check_no_part_overlaps()

    return ctx.report()


# >>> USER_CODE_END

object_model = build_object_model()
