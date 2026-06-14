"""Endpoint presets and target resolution for the provider layer.

This module is the keystone of the protocol/endpoint/served_by model:

- ``Protocol`` (defined in ``articraft.values``) is *how* we talk to a model.
- An *endpoint* is *where* the request goes: a ``base_url`` plus which API-key env var
  carries credentials.
- ``served_by`` is *who* actually serves the weights (the real attribution).

Historically these three were collapsed into a single ``provider`` enum value. Each of
those legacy values is preserved here as a named endpoint preset so existing CLIs, batch
CSVs, and records keep working, while new callers can also supply an ad-hoc endpoint
(``base_url`` + ``api_key_env``) to point Articraft at any OpenAI-compatible server,
including a local one (vLLM / Ollama / LM Studio / llama.cpp).
"""

from __future__ import annotations

from dataclasses import dataclass

from articraft.values import Protocol

# Sentinel base_url values for protocols that do not speak plain HTTP base URLs.
SDK_BASE_URL = "(sdk)"
SUBPROCESS_BASE_URL = "(subprocess)"


@dataclass(slots=True, frozen=True)
class EndpointPreset:
    """A named bundle of protocol + where-to-send + default attribution."""

    name: str
    protocol: Protocol
    base_url: str
    api_key_env: str | None
    # None means served_by is not known up front (e.g. OpenRouter routes downstream and
    # reports the real backend only in the response).
    served_by: str | None


# Legacy provider names are retained as endpoint presets so nothing downstream breaks.
_PRESETS: tuple[EndpointPreset, ...] = (
    EndpointPreset(
        name="openai",
        protocol=Protocol.OPENAI_RESPONSES,
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        served_by="OpenAI",
    ),
    EndpointPreset(
        name="openrouter",
        protocol=Protocol.OPENAI_CHAT,
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        served_by=None,  # read from response
    ),
    EndpointPreset(
        name="deepseek",
        protocol=Protocol.OPENAI_CHAT,
        base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        served_by="DeepSeek",
    ),
    EndpointPreset(
        name="dashscope",
        protocol=Protocol.OPENAI_CHAT,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        served_by="Alibaba",
    ),
    EndpointPreset(
        name="anthropic",
        protocol=Protocol.ANTHROPIC_MESSAGES,
        base_url="https://api.anthropic.com",
        api_key_env="ANTHROPIC_API_KEY",
        served_by="Anthropic",
    ),
    EndpointPreset(
        name="gemini",
        protocol=Protocol.GEMINI,
        base_url=SDK_BASE_URL,
        api_key_env="GEMINI_API_KEYS",
        served_by="Google",
    ),
    EndpointPreset(
        name="codex-cli",
        protocol=Protocol.CODEX_CLI,
        base_url=SUBPROCESS_BASE_URL,
        api_key_env=None,
        served_by="OpenAI",
    ),
)

PRESETS_BY_NAME: dict[str, EndpointPreset] = {preset.name: preset for preset in _PRESETS}
PRESET_NAMES: tuple[str, ...] = tuple(PRESETS_BY_NAME)


@dataclass(slots=True, frozen=True)
class ResolvedTarget:
    """Fully resolved generation target, ready for the factory and persistence."""

    protocol: Protocol
    model: str
    endpoint: str  # preset name, or the raw base_url for ad-hoc endpoints
    base_url: str
    api_key_env: str | None
    served_by: str | None


# Substring → served_by inference for direct (non-OpenRouter) endpoints.
_SERVED_BY_BY_HOST: tuple[tuple[str, str], ...] = (
    ("openrouter.ai", ""),  # empty => unknown up front; read from response
    ("api.openai.com", "OpenAI"),
    ("api.anthropic.com", "Anthropic"),
    ("api.deepseek.com", "DeepSeek"),
    ("aliyuncs.com", "Alibaba"),
    ("dashscope", "Alibaba"),
    ("generativelanguage.googleapis.com", "Google"),
)


def served_by_from_base_url(base_url: str | None) -> str | None:
    """Best-effort served_by from an endpoint base_url; None when unknown."""

    host = (base_url or "").strip().lower()
    if not host:
        return None
    for needle, served_by in _SERVED_BY_BY_HOST:
        if needle in host:
            return served_by or None
    return None


def get_preset(name: str | None) -> EndpointPreset | None:
    return PRESETS_BY_NAME.get((name or "").strip().lower())


def infer_endpoint_from_model(model: str | None) -> str | None:
    """Infer an endpoint preset name from a model id, mirroring legacy inference.

    Returns a preset name (e.g. ``"openai"``) or None when no rule matches.
    """

    model_norm = (model or "").strip().lower()
    if not model_norm:
        return None
    if model_norm.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    if model_norm.startswith("claude-"):
        return "anthropic"
    if model_norm.startswith(("codex-cli", "codex/")):
        return "codex-cli"
    if model_norm.startswith("qwen"):
        return "dashscope"
    if model_norm.startswith("gemini-"):
        return "gemini"
    if model_norm.startswith("deepseek-"):
        return "deepseek"
    if "/" in model_norm or model_norm.startswith("openrouter/"):
        return "openrouter"
    return None


def split_model_prefix(model: str) -> tuple[str | None, str]:
    """Split an optional ``preset:`` prefix off a model spec.

    Only splits when the text before the first ``:`` is a known preset name, so that
    suffixes like ``...:free`` and ids like ``gpt-5.5-2026-04-23`` are left intact.
    Returns ``(preset_name_or_None, model)``.
    """

    if ":" not in model:
        return None, model
    candidate, rest = model.split(":", 1)
    if candidate.strip().lower() in PRESETS_BY_NAME and rest.strip():
        return candidate.strip().lower(), rest.strip()
    return None, model


def resolve_target(
    *,
    model: str | None,
    endpoint: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
    protocol: str | Protocol | None = None,
    served_by: str | None = None,
) -> ResolvedTarget:
    """Resolve a generation target from any combination of user inputs.

    Precedence for choosing the endpoint:
      1. ``preset:`` prefix embedded in ``model``.
      2. Explicit ``endpoint`` preset name.
      3. Ad-hoc ``base_url`` (+ ``api_key_env``); protocol defaults to ``openai-chat``.
      4. Inference from the model id.
    An explicit ``served_by`` always overrides inference.
    """

    model_value = (model or "").strip()

    if model_value:
        prefixed_preset, model_value = split_model_prefix(model_value)
        if prefixed_preset and not endpoint:
            endpoint = prefixed_preset

    # Ad-hoc endpoint (the local-model path): base_url given without a preset.
    if base_url and not endpoint:
        proto = Protocol(str(protocol)) if protocol is not None else Protocol.OPENAI_CHAT
        return ResolvedTarget(
            protocol=proto,
            model=model_value,
            endpoint=base_url.rstrip("/"),
            base_url=base_url.rstrip("/"),
            api_key_env=api_key_env,
            served_by=served_by or served_by_from_base_url(base_url),
        )

    preset_name = (endpoint or "").strip().lower() or infer_endpoint_from_model(model_value)
    preset = get_preset(preset_name) if preset_name else None
    if preset is None:
        raise ValueError(
            f"Could not resolve an endpoint for model={model!r}. "
            f"Pass --endpoint <{'|'.join(PRESET_NAMES)}> or --base-url <url>."
        )

    resolved_protocol = Protocol(str(protocol)) if protocol is not None else preset.protocol
    resolved_base_url = base_url.rstrip("/") if base_url else preset.base_url
    return ResolvedTarget(
        protocol=resolved_protocol,
        model=model_value,
        endpoint=preset.name,
        base_url=resolved_base_url,
        api_key_env=api_key_env or preset.api_key_env,
        served_by=served_by or preset.served_by,
    )
