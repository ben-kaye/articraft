"""The agentic loop: prompt the model, run its tool calls, iterate until it stops or limits hit."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import gittrack, guidance, llm, tools
from .compiler import CompileResult, compile_model
from .prompts import RUNTIME_GUIDANCE, build_sdk_docs_context, build_system_prompt


@dataclass
class AgentResult:
    success: bool
    model_py: str
    urdf_xml: str | None
    compile: CompileResult
    turns: int
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    terminate_reason: str = "done"
    trace: list[dict] = field(default_factory=list)


def _trace_call(name: str, args: dict, result: str) -> dict:
    """Trace entry for one tool call, minus payloads recoverable from the per-turn model.py
    snapshots in .modelgit. read_file's result and write_file's `content` arg are the bulk of
    trace size and fully reconstructable, so we record their length instead of the body."""
    call: dict = {"name": name, "args": args, "result": result}
    if name == "read_file":
        call["result"] = f"<{len(result)} chars; see model.py snapshot or SDK docs>"
        call["viewed_ids"] = [args.get("path") or "model.py"]
    elif name == "write_file":
        content = args.get("content", "")
        call["args"] = {**args, "content": f"<{len(content)} chars; see turn snapshot>"}
    elif name == "find_examples":
        # find returns each hit under a "===== example <ref> =====" header (runner._make_find_examples).
        call["viewed_ids"] = re.findall(r"^===== example (.+?) =====$", result, re.MULTILINE)
    return call


def _image_content(image_path: Path) -> dict:
    mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


class ArticraftAgent:
    def __init__(
        self,
        workspace: tools.Workspace,
        *,
        model: str,
        thinking_level: str = "medium",
        sdk_package: str = "sdk",
        max_turns: int = 40,
        max_cost_usd: float | None = None,
        max_stall_turns: int = 3,
    ):
        self.ws = workspace
        self.model = model
        self.thinking_level = thinking_level
        self.sdk_package = sdk_package
        self.max_turns = max_turns
        self.max_cost_usd = max_cost_usd
        self.max_stall_turns = max_stall_turns

    def run(
        self,
        prompt: str,
        *,
        image_path: Path | None = None,
        on_turn: Callable[[list[dict], int, int, int, float], None] | None = None,
    ) -> AgentResult:
        # First-turn message stream mirrors articraft's openai build_first_turn_messages: the SDK docs ride
        # in their own user message, and the runtime guidance is prepended to the user's prompt.
        user_content: str | list[dict]
        if image_path is None:
            user_content = f"{RUNTIME_GUIDANCE}\n\n{prompt}"
        else:
            user_content = [
                {"type": "text", "text": RUNTIME_GUIDANCE},
                {"type": "text", "text": prompt},
                _image_content(image_path),
            ]
        messages: list[dict] = [
            {"role": "system", "content": build_system_prompt(self.sdk_package)},
            {"role": "user", "content": build_sdk_docs_context(self.sdk_package)},
            {"role": "user", "content": user_content},
        ]

        in_tok = out_tok = cache_tok = 0
        cost = 0.0
        reason = "done"
        turn_no = 0
        trace: list[dict] = []
        stall = 0  # consecutive compile-only turns that left model.py unchanged
        seen_guidance: set[str] = set()  # proactive nudges already fired (fire once each)
        compile_nudged = False  # G1 compile-required reminder fired (once per run)

        def model_sha() -> str | None:
            return (
                hashlib.sha256(self.ws.model_path.read_bytes()).hexdigest()
                if self.ws.model_path.exists()
                else None
            )

        prev_sha = model_sha()
        gittrack.snapshot(self.ws.model_path, "seed")
        # Responses-API models keep reasoning server-side: send only new messages each turn and
        # chain by response id, instead of re-sending the whole history (the completion path).
        responses_mode = llm.uses_responses(self.model)
        prev_response_id: str | None = None
        sent = 0
        for turn_no in range(1, self.max_turns + 1):
            # Responses applies `instructions` per-call, so always resend the system prompt
            # (messages[0]); only the conversation delta is new each turn (OpenAI caches the rest).
            if responses_mode:
                payload = messages[sent:] if sent == 0 else [messages[0], *messages[sent:]]
            else:
                payload = messages
            sent = len(messages)
            try:
                turn = llm.call(
                    payload,
                    model=self.model,
                    tools=tools.schemas(self.ws, self.model),
                    thinking_level=self.thinking_level,
                    previous_response_id=prev_response_id,
                )
                prev_response_id = turn.response_id or prev_response_id
            except llm.ImageInputUnsupported:
                raise  # config error, not a transient failure — surface it, don't bury in a trace
            except Exception as exc:  # noqa: BLE001 — terminate the run cleanly, don't crash the batch
                reason = "error"
                trace.append({"turn": turn_no, "error": f"{type(exc).__name__}: {exc}"})
                if on_turn is not None:
                    on_turn(trace, in_tok, out_tok, cache_tok, cost)
                break
            in_tok += turn.input_tokens
            out_tok += turn.output_tokens
            cache_tok += turn.cache_read_tokens
            cost += turn.cost_usd
            messages.append(turn.message)

            entry = {
                "turn": turn_no,
                "text": turn.text,
                "reasoning": turn.reasoning,
                "provider": turn.provider,
                "input_tokens": turn.input_tokens,
                "output_tokens": turn.output_tokens,
                "cache_read_tokens": turn.cache_read_tokens,
                "cost_usd": turn.cost_usd,
                "tool_calls": [],
            }
            trace.append(entry)

            if not turn.tool_calls:
                # G1: if the model tries to conclude on edits it never compiled, nudge it to compile
                # first (articraft's compile_required reminder). Once per run — the final authoritative
                # compile still fixes the success label regardless, so this only shapes trace-ending
                # state, and re-nudging a model that ignores it would just loop to max_turns.
                stale = self.ws.model_path.exists() and model_sha() != self.ws.last_compile_sha
                if stale and not compile_nudged:
                    compile_nudged = True
                    nudge = (
                        "<compile_required>\n"
                        "model.py has edits that were never compiled. Run `compile_model` to verify "
                        "them before concluding.\n"
                        "</compile_required>"
                    )
                    messages.append({"role": "user", "content": nudge})
                    entry["guidance"] = [*entry.get("guidance", []), nudge]
                    if on_turn is not None:
                        on_turn(trace, in_tok, out_tok, cache_tok, cost)
                    continue
                reason = "model_stopped"
                if on_turn is not None:
                    on_turn(trace, in_tok, out_tok, cache_tok, cost)
                break

            for tc in turn.tool_calls:
                result = tools.dispatch(tc.name, self.ws, tc.args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                call = _trace_call(tc.name, tc.args, result)
                if tc.name == "compile_model" and self.ws.last_compile is not None:
                    c = self.ws.last_compile
                    call["compile"] = {
                        "ok": c.ok,
                        "passed": c.passed,
                        "failures": c.failures,
                        "warnings": c.warnings,
                    }
                entry["tool_calls"].append(call)

            gittrack.snapshot(self.ws.model_path, f"turn {turn_no}")

            # Proactive pre-compile nudges: after a mutating turn, scan model.py for stale
            # exact-geometry contracts or baseline QC re-implemented in run_tests(), and push the
            # finding now instead of waiting for compile to surface it a turn later. Fires once each.
            if {tc.name for tc in turn.tool_calls} & {"str_replace", "apply_patch", "write_file"} and self.ws.model_path.exists():
                nudges = guidance.guidance_messages(
                    self.ws.model_path.read_text(encoding="utf-8"), seen_guidance
                )
                if nudges:
                    messages.append({"role": "user", "content": "\n\n".join(nudges)})
                    entry["guidance"] = nudges

            if on_turn is not None:
                on_turn(trace, in_tok, out_tok, cache_tok, cost)

            if self.max_cost_usd is not None and cost >= self.max_cost_usd:
                reason = "cost_limit"
                break

            cur_sha = model_sha()
            # Only spinning on compile (no edit) counts as a stall. Reading docs or
            # other non-edit exploration is allowed and leaves the counter untouched.
            names = {tc.name for tc in turn.tool_calls}
            if cur_sha != prev_sha:
                stall = 0
            elif names == {"compile_model"}:
                stall += 1
            prev_sha = cur_sha
            if stall >= self.max_stall_turns:
                reason = "stall"
                break
        else:
            reason = "max_turns"

        # Final authoritative compile.
        compiled = (
            compile_model(self.ws.model_path, repo_root=self.ws.repo_root)
            if self.ws.model_path.exists()
            else CompileResult(ok=False, passed=False, error="no model.py produced")
        )
        return AgentResult(
            success=compiled.passed,
            model_py=self.ws.model_path.read_text(encoding="utf-8")
            if self.ws.model_path.exists()
            else "",
            urdf_xml=compiled.urdf_xml,
            compile=compiled,
            turns=turn_no,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cache_read_tokens=cache_tok,
            cost_usd=cost,
            terminate_reason=reason,
            trace=trace,
        )
