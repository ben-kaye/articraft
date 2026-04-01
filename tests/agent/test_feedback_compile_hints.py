from __future__ import annotations

from agent.feedback import build_compile_signal_bundle, render_compile_signals


def test_compile_signal_bundle_includes_loft_hint() -> None:
    exc = RuntimeError(
        "ValueError: Loft profile area must be non-zero in XY projection; "
        "profiles should usually be closed XY loops at constant z"
    )
    rendered = render_compile_signals(build_compile_signal_bundle(status="failure", exc=exc))

    assert "<compile_signals>" in rendered
    assert "Loft profile area must be non-zero in XY projection" in rendered
    assert "Hint: LoftGeometry checks profile area in the XY projection." in rendered
    assert "author it in XY first and rotate the mesh afterward" in rendered


def test_render_compile_signals_clean_success_uses_summary_only_block() -> None:
    rendered = render_compile_signals(build_compile_signal_bundle(status="success"))

    assert rendered == (
        "<compile_signals>\n"
        "<summary>\n"
        "status=success failures=0 warnings=0 notes=0\n"
        "Compile passed cleanly.\n"
        "</summary>\n"
        "</compile_signals>"
    )
