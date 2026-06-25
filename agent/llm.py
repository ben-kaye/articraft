"""LLM interface. Native Anthropic SDK for Claude; litellm for everything else.

- **Anthropic** (`_call_anthropic`): native Messages API — *necessary*, not a preference. litellm
  does not handle Anthropic first-class: its completion path drops the model's *signed thinking
  blocks*, so we can't round-trip them across tool-use turns or run **interleaved thinking**, and
  our 4 thinking levels collapse to 3 under its `reasoning_effort` mapping. Native gives us all of
  that. (Verified against litellm 1.89.2; recheck if a much newer litellm closes the gap.)
- **OpenAI reasoning / gpt-5** (`_call_responses`): Responses API via `litellm.responses` — already
  first-class there (server-side reasoning persistence via `store=True` + `previous_response_id`),
  so no native SDK needed. Gated by `uses_responses`.
- **Everything else** (`_call_litellm`): deepinfra / openrouter / bedrock / vertex Claude / etc.

The public surface — `call() -> Turn`, `route`, `uses_responses`, `ImageInputUnsupported` — is
stable; `harness.py` is provider-agnostic and never changes per path.

POTENTIAL BUG: a stalled provider connection can hang a whole generation. We cap each request
with timeout=300 (below), but a 5-min stall per turn is still slow, and a flaky provider can burn
the retry budget timing out. If runs wedge again, revisit the timeout / num_retries / concurrency.

NO COMPACTION: the old articraft `providers/` package had a context-pressure/compaction layer
(`compaction_policy.py`, `ContextWindowPressure`); this rewrite dropped it. Runs exit only on
max-turns / max-cost. The Responses path (`store=True` + `previous_response_id`) grows server-side
state uncapped across the compile→edit loop, so a long stubborn gpt-5/o-series run can die with a
context-length provider error rather than a clean exit. Lazy fix if that shows up: drop
`previous_response_id` on a turn/token threshold (fresh chain) — not the 223-line policy engine.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import litellm

from articraft.values import ThinkingLevel, normalize_thinking_level

litellm.drop_params = True  # providers without reasoning_effort (e.g. deepinfra) just drop it

# litellm/OpenAI reasoning_effort accepts low/medium/high; map our 4 levels onto those.
_EFFORT = {
    ThinkingLevel.LOW: "low",
    ThinkingLevel.MED: "medium",
    ThinkingLevel.HIGH: "high",
    ThinkingLevel.XHIGH: "high",
}

# Native Anthropic thinking budgets (tokens) — our 4 levels stay distinct here, unlike _EFFORT
# where xhigh collapses into high. budget_tokens may exceed max_tokens under interleaved thinking.
_ANTHROPIC_BUDGET = {
    ThinkingLevel.LOW: 4_000,
    ThinkingLevel.MED: 10_000,
    ThinkingLevel.HIGH: 20_000,
    ThinkingLevel.XHIGH: 30_000,
}
# ponytail: fixed ceiling; raise if models start truncating final output. Interleaved thinking lets
# the thinking budget above exceed this, so this bounds the *post-thinking* answer + tool args.
_ANTHROPIC_MAX_TOKENS = 32_000
_INTERLEAVED_THINKING_BETA = "interleaved-thinking-2025-05-14"

_anthropic_client = None


def _anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic

        # Honor litellm's env-var name for a custom base (e.g. a proxy) so routing matches the
        # rest of the stack; the native SDK only reads ANTHROPIC_BASE_URL on its own.
        _anthropic_client = anthropic.Anthropic(base_url=os.getenv("ANTHROPIC_API_BASE") or None)
    return _anthropic_client


class ImageInputUnsupported(Exception):
    """Raised when a routed model rejects image input (non-vision model + --image)."""


def _has_image(messages: list[dict]) -> bool:
    return any(
        isinstance(b, dict) and b.get("type") == "image_url"
        for m in messages
        for b in (m["content"] if isinstance(m["content"], list) else [])
    )


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Turn:
    message: dict  # raw assistant message, append verbatim to the conversation
    text: str
    provider: str = ""  # OpenRouter upstream provider (e.g. "DeepInfra") — quant/perf varies by it
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    response_id: str = ""  # Responses-API chain id; "" on the completion path
    reasoning: str = ""  # human-readable reasoning summary (OpenAI raw CoT is encrypted; only summaries are exposed)


def route(model: str) -> str:
    """Force the provider so unknown/future model ids still resolve."""
    if "/" in model:
        return model
    if model.startswith("claude"):
        return f"anthropic/{model}"
    if model.startswith(("gpt", "o1", "o3", "o4")):
        return f"openai/{model}"
    return model


def uses_responses(model: str) -> bool:
    """Direct-OpenAI reasoning models go through the Responses API so reasoning state persists
    across the compile→edit loop. OpenRouter-routed OpenAI stays on completion (no persistence
    there anyway). gpt-5-chat-latest has no reasoning but still works fine through Responses."""
    routed = route(model)
    if not routed.startswith("openai/"):
        return False
    return routed.split("/", 1)[1].startswith(("gpt-5", "o1", "o3", "o4"))


def provider_kind(model: str) -> str:
    """Which code path: native 'anthropic' SDK vs 'litellm' for everything else (the OpenAI
    Responses path lives inside the litellm branch, gated by uses_responses). bedrock/vertex-routed
    Claude stays on litellm — only direct anthropic/* goes native."""
    routed = route(model)
    if routed.startswith("anthropic/") and routed.split("/", 1)[1].startswith("claude"):
        return "anthropic"
    return "litellm"


_CACHE = {"type": "ephemeral"}


def _as_blocks(content) -> list[dict]:
    """Normalize a message's content to a list of blocks so we can tag the last one."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [dict(b) for b in content]  # copy so we don't mutate the caller's history


def _with_cache_breakpoints(messages: list[dict], tools: list[dict] | None):
    """Mark the cacheable prefix for Anthropic prompt caching: the static system prompt +
    tool schemas, plus a rolling breakpoint on the latest message. Anthropic matches the
    longest cached prefix, so each turn reads the prior turn's prefix and writes the new one.
    Returns fresh lists; the caller's growing history is never mutated.
    ponytail: 3 of the 4 allowed breakpoints — system, tools, and tail. Add a per-turn
    marker only if cache writes start churning on very long runs."""
    msgs = [dict(m) for m in messages]
    for m in msgs:  # cache the system prompt (large, identical every turn)
        if m.get("role") == "system":
            blocks = _as_blocks(m["content"])
            blocks[-1] = {**blocks[-1], "cache_control": _CACHE}
            m["content"] = blocks
    if msgs:  # rolling breakpoint on the most recent message
        last = msgs[-1]
        blocks = _as_blocks(last["content"])
        blocks[-1] = {**blocks[-1], "cache_control": _CACHE}
        last["content"] = blocks
    cached_tools = tools
    if tools:  # cache the tool schemas (also identical every turn)
        cached_tools = [dict(t) for t in tools]
        cached_tools[-1] = {**cached_tools[-1], "cache_control": _CACHE}
    return msgs, cached_tools


def call(
    messages: list[dict],
    *,
    model: str,
    tools: list[dict] | None = None,
    thinking_level: str | None = "medium",
    max_retries: int = 3,
    previous_response_id: str | None = None,
) -> Turn:
    level = normalize_thinking_level(thinking_level)
    effort = _EFFORT[level]
    routed = route(model)
    if provider_kind(model) == "anthropic":
        return _call_anthropic(
            messages, routed=routed, tools=tools, level=level, max_retries=max_retries
        )
    if uses_responses(model):  # responses-capable models keep server-side reasoning state
        return _call_responses(
            messages,
            routed=routed,
            tools=tools,
            effort=effort,
            max_retries=max_retries,
            previous_response_id=previous_response_id,
        )
    return _call_litellm(
        messages, routed=routed, tools=tools, effort=effort, max_retries=max_retries
    )


def _call_litellm(
    messages: list[dict],
    *,
    routed: str,
    tools: list[dict] | None,
    effort: str,
    max_retries: int,
) -> Turn:
    # Prompt caching is Anthropic-only here; for other providers drop_params strips it, but
    # the block-form content/tools could confuse them, so only transform for Anthropic.
    if routed.startswith("anthropic/"):
        messages, tools = _with_cache_breakpoints(messages, tools)
    # OpenRouter only returns spend if you ask for it; harmless elsewhere (drop_params strips it).
    extra_body = {"usage": {"include": True}} if routed.startswith("openrouter/") else None
    try:
        resp = litellm.completion(
            model=routed,
            messages=messages,
            tools=tools or None,
            reasoning_effort=effort,
            num_retries=max_retries,
            extra_body=extra_body,
            timeout=300,  # per-request; without this a stalled provider connection hangs the run forever
        )
    except Exception as exc:
        if _has_image(messages) and "image" in str(exc).lower():
            raise ImageInputUnsupported(
                f"{routed} rejected image input; drop --image or pick a vision model"
            ) from exc
        raise
    msg = resp.choices[0].message
    tool_calls = []
    for tc in msg.tool_calls or []:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, args=args))

    usage = resp.usage or {}
    # Providers that report actual spend: OpenRouter on usage.cost, DeepInfra on estimated_cost.
    cost = getattr(usage, "cost", None) or getattr(usage, "estimated_cost", None)
    if not cost:
        try:
            cost = litellm.completion_cost(resp) or 0.0
        except Exception:  # unknown model pricing — don't crash the run
            cost = 0.0

    out_tokens = getattr(usage, "completion_tokens", 0) or 0
    if not cost and out_tokens:  # paid run that reports free = dropped pricing, flag it
        import warnings

        warnings.warn(f"no cost for {routed} ({out_tokens} output tokens)")

    details = getattr(usage, "prompt_tokens_details", None)
    cache_read = getattr(details, "cached_tokens", 0) or 0 if details else 0

    # OpenRouter routes to varying upstream providers (different quant/throughput); it echoes the
    # chosen one as top-level `provider`. litellm surfaces unmapped fields on _hidden_params.
    provider = (
        getattr(resp, "provider", "")
        or (getattr(resp, "_hidden_params", None) or {}).get("provider", "")
        or ""
    )

    return Turn(
        message=msg.model_dump(),
        text=msg.content or "",
        provider=provider,
        tool_calls=tool_calls,
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=out_tokens,
        cache_read_tokens=cache_read,
        cost_usd=cost,
        reasoning=getattr(msg, "reasoning_content", "") or "",
    )


def _to_responses_input(messages: list[dict]) -> tuple[str, list[dict]]:
    """Convert chat-completions messages into (instructions, input items) for the Responses API.
    Assistant messages are dropped — they live server-side once chained by previous_response_id."""
    instructions: list[str] = []
    items: list[dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "system":
            instructions.append(
                content
                if isinstance(content, str)
                else " ".join(b.get("text", "") for b in content if isinstance(b, dict))
            )
        elif role == "assistant":
            continue  # already on the server via the response chain
        elif role == "tool":
            items.append(
                {"type": "function_call_output", "call_id": m["tool_call_id"], "output": content}
            )
        elif isinstance(content, str):
            items.append({"role": role, "content": content})
        else:  # content blocks: text / image_url -> Responses input_text / input_image
            blocks = []
            for b in content:
                if b.get("type") == "text":
                    blocks.append({"type": "input_text", "text": b["text"]})
                elif b.get("type") == "image_url":
                    blocks.append({"type": "input_image", "image_url": b["image_url"]["url"]})
            items.append({"role": role, "content": blocks})
    return "\n\n".join(i for i in instructions if i), items


def _to_responses_tools(tools: list[dict] | None) -> list[dict] | None:
    """Flatten chat-completions {"type":"function","function":{...}} to the Responses shape."""
    if not tools:
        return None
    return [
        {
            "type": "function",
            "name": t["function"]["name"],
            "description": t["function"].get("description", ""),
            "parameters": t["function"].get("parameters", {}),
        }
        for t in tools
    ]


def _call_responses(
    messages: list[dict],
    *,
    routed: str,
    tools: list[dict] | None,
    effort: str,
    max_retries: int,
    previous_response_id: str | None,
) -> Turn:
    instructions, items = _to_responses_input(messages)
    try:
        resp = litellm.responses(
            model=routed,
            input=items,
            instructions=instructions or None,
            tools=_to_responses_tools(tools),
            reasoning={"effort": effort, "summary": "auto"},  # summary = the only plaintext CoT we get
            previous_response_id=previous_response_id,
            store=True,  # ponytail: server-side state for reasoning persistence; 30-day retention.
            num_retries=max_retries,
            timeout=300,
        )
    except Exception as exc:
        if _has_image(messages) and "image" in str(exc).lower():
            raise ImageInputUnsupported(
                f"{routed} rejected image input; drop --image or pick a vision model"
            ) from exc
        raise

    text_parts, reasoning_parts, tool_calls = [], [], []
    for o in resp.output:
        d = o.model_dump() if hasattr(o, "model_dump") else o
        if d.get("type") == "message":
            text_parts += [
                c.get("text", "") for c in d.get("content", []) if c.get("type") == "output_text"
            ]
        elif d.get("type") == "reasoning":
            reasoning_parts += [
                s.get("text", "") for s in d.get("summary", []) if s.get("type") == "summary_text"
            ]
        elif d.get("type") == "function_call":
            try:
                args = json.loads(d.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=d["call_id"], name=d["name"], args=args))
    text = "".join(text_parts)
    reasoning = "\n".join(p for p in reasoning_parts if p)

    # Re-encode as a chat-completions assistant message so the harness trace/append path is uniform.
    # It's never resent (assistant messages are dropped on the next _to_responses_input).
    msg: dict = {"role": "assistant", "content": text}
    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.args)},
            }
            for tc in tool_calls
        ]

    u = resp.usage.model_dump() if hasattr(resp.usage, "model_dump") else dict(resp.usage or {})
    cost = u.get("cost")
    if not cost:
        try:
            cost = litellm.completion_cost(resp) or 0.0
        except Exception:
            cost = 0.0
    return Turn(
        message=msg,
        text=text,
        tool_calls=tool_calls,
        input_tokens=u.get("input_tokens", 0) or 0,
        output_tokens=u.get("output_tokens", 0) or 0,
        cache_read_tokens=(u.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0,
        cost_usd=cost or 0.0,
        response_id=resp.id,
        reasoning=reasoning,
    )


def _cost(routed: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Price native-SDK usage via litellm's pricing map (its completion_cost only takes litellm
    objects). ponytail: bills cached reads at full input rate — a small overestimate, acceptable
    for cost tracking; switch to litellm's cache_read_input_tokens kwarg if it ever matters."""
    try:
        prompt_cost, completion_cost = litellm.cost_per_token(
            model=routed, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )
        return (prompt_cost or 0.0) + (completion_cost or 0.0)
    except Exception:  # unknown model pricing — don't crash the run
        return 0.0


# ── Anthropic native path ────────────────────────────────────────────────────────────────────


def _anthropic_user_blocks(content) -> list[dict]:
    """A chat user message's content → Anthropic user content blocks (text / image)."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    blocks = []
    for b in content:
        if b.get("type") == "text":
            blocks.append({"type": "text", "text": b["text"]})
        elif b.get("type") == "image_url":
            # harness sends data URLs: "data:image/png;base64,<b64>" -> Anthropic base64 source.
            url = b["image_url"]["url"]
            header, _, data = url.partition(",")
            media_type = header[len("data:") :].split(";", 1)[0] or "image/png"
            blocks.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": data},
                }
            )
    return blocks


def _to_anthropic(messages: list[dict]) -> tuple[list[dict] | None, list[dict]]:
    """Chat-completions messages → (system blocks, Anthropic messages). System text is hoisted to
    the top-level `system` param; consecutive user/tool messages merge into one user turn (so
    tool_result blocks and any following user text share a message, as Anthropic expects)."""
    system_parts: list[str] = []
    out: list[dict] = []
    pending: list[dict] = []  # accumulating user-side blocks until the next assistant turn

    def flush():
        if pending:
            out.append({"role": "user", "content": list(pending)})
            pending.clear()

    for m in messages:
        role, content = m.get("role"), m.get("content")
        if role == "system":
            system_parts.append(
                content
                if isinstance(content, str)
                else " ".join(b.get("text", "") for b in content if isinstance(b, dict))
            )
        elif role == "assistant":
            flush()
            if m.get("_anthropic_blocks"):  # signed thinking/text/tool_use, resent verbatim
                out.append({"role": "assistant", "content": m["_anthropic_blocks"]})
                continue
            blocks: list[dict] = []
            if isinstance(content, str) and content:
                blocks.append({"type": "text", "text": content})
            elif isinstance(content, list):
                blocks += [
                    {"type": "text", "text": b["text"]}
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
            for tc in m.get("tool_calls") or []:
                fn = tc["function"]
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                blocks.append(
                    {"type": "tool_use", "id": tc["id"], "name": fn["name"], "input": args}
                )
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
        elif role == "tool":
            pending.append(
                {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": content}
            )
        else:  # user
            pending += _anthropic_user_blocks(content)
    flush()
    system = (
        [{"type": "text", "text": "\n\n".join(p for p in system_parts if p)}]
        if system_parts
        else None
    )
    return system, out


def _to_anthropic_tools(tools: list[dict] | None) -> list[dict] | None:
    """Chat-completions tool schemas → Anthropic tool schemas."""
    if not tools:
        return None
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"].get("description", ""),
            "input_schema": t["function"].get("parameters", {}),
        }
        for t in tools
    ]


_CACHEABLE_TAIL = {"text", "tool_result", "image"}  # never tag a signed thinking block


def _call_anthropic(
    messages: list[dict],
    *,
    routed: str,
    tools: list[dict] | None,
    level: ThinkingLevel,
    max_retries: int,
) -> Turn:
    system, amsgs = _to_anthropic(messages)
    atools = _to_anthropic_tools(tools)
    # Prompt-cache breakpoints: system, tools, and a rolling tail (Anthropic matches the longest
    # cached prefix). Copy before tagging so the caller's history is never mutated.
    if system:
        system = [*system[:-1], {**system[-1], "cache_control": _CACHE}]
    if atools:
        atools = [*atools[:-1], {**atools[-1], "cache_control": _CACHE}]
    if amsgs:
        blocks = amsgs[-1]["content"]
        if isinstance(blocks, list) and blocks and blocks[-1].get("type") in _CACHEABLE_TAIL:
            tail = {**amsgs[-1], "content": [*blocks[:-1], {**blocks[-1], "cache_control": _CACHE}]}
            amsgs = [*amsgs[:-1], tail]

    has_image = _has_image(messages)
    kwargs: dict = {
        "model": routed.split("/", 1)[1],  # native SDK wants the bare id, not "anthropic/..."
        "max_tokens": _ANTHROPIC_MAX_TOKENS,
        "messages": amsgs,
        # Interleaved thinking: thinking blocks persist across tool turns (via _anthropic_blocks)
        # and the budget may exceed max_tokens.
        "thinking": {"type": "enabled", "budget_tokens": _ANTHROPIC_BUDGET[level]},
        "extra_headers": {"anthropic-beta": _INTERLEAVED_THINKING_BETA},
    }
    if system:
        kwargs["system"] = system
    if atools:
        kwargs["tools"] = atools
    client = _anthropic().with_options(max_retries=max_retries, timeout=300)
    try:
        resp = client.messages.create(**kwargs)
    except Exception as exc:
        if has_image and "image" in str(exc).lower():
            raise ImageInputUnsupported(
                f"{routed} rejected image input; drop --image or pick a vision model"
            ) from exc
        raise

    text_parts, thinking_parts, tool_calls, raw_blocks = [], [], [], []
    for b in resp.content:
        d = b.model_dump()
        raw_blocks.append(
            d
        )  # verbatim, signatures intact — resent next turn for interleaved thinking
        t = d.get("type")
        if t == "text":
            text_parts.append(d.get("text", ""))
        elif t == "thinking":
            thinking_parts.append(d.get("thinking", ""))
        elif t == "tool_use":
            tool_calls.append(ToolCall(id=d["id"], name=d["name"], args=d.get("input") or {}))
    text = "".join(text_parts)

    msg: dict = {"role": "assistant", "content": text, "_anthropic_blocks": raw_blocks}
    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.args)},
            }
            for tc in tool_calls
        ]

    u = resp.usage
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    cache_create = getattr(u, "cache_creation_input_tokens", 0) or 0
    # Match the completion path's semantics: input_tokens = total input incl. cached prefix.
    in_tok = (u.input_tokens or 0) + cache_read + cache_create
    out_tok = u.output_tokens or 0
    return Turn(
        message=msg,
        text=text,
        tool_calls=tool_calls,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cache_read_tokens=cache_read,
        cost_usd=_cost(routed, in_tok, out_tok),
        reasoning="\n".join(p for p in thinking_parts if p),
    )
