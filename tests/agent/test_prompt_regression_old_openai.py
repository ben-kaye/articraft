from __future__ import annotations

from agent.prompts.compile import compile_prompt_variant
from agent.prompts.spec import iter_prompt_variants


def test_compiled_openai_prompt_keeps_compact_contract_and_visual_test_gate() -> None:
    variant = next(
        variant
        for variant in iter_prompt_variants()
        if variant.output.name == "designer_system_prompt_openai.txt"
    )
    compiled = compile_prompt_variant(variant)
    generated = variant.output.read_text(encoding="utf-8")

    for text in (compiled, generated):
        assert "<role>" in text
        assert "<tool_contract>" in text
        assert "<modeling_charter>" in text
        assert "<verification_contract>" in text
        assert "<repair_strategy>" in text
        assert "Use ONLY `read_file`, `apply_patch`, `probe_model`, and `find_examples`" in text
        assert "probe_model` runs short Python snippets against the current bound model" in text
        assert "lexical search over curated base SDK examples" in text
        assert "Use the injected SDK docs for exact helper signatures" in text
        assert (
            "The model is not done until every applicable visual coverage category is proved"
            in text
        )
        assert "hero features are present" in text
        assert "connected/seated" in text
        assert "important parts are in the right place" in text
        assert "each new visible form or mechanism has a matching assertion" in text
        assert "complexity is a feature, not a bug" in text
        assert "Do not cap a visible opening with a solid placeholder primitive." in text
        assert "expect_aabb_" not in text
        assert "expect_joint_motion_axis(" not in text
        assert len(text.splitlines()) <= 132
