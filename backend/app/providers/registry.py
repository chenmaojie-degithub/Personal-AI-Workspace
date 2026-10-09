from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


VERIFIED_OPENROUTER_TOOL_MODELS = frozenset({
    "nvidia/nemotron-3-super-120b-a12b:free",
})


def _supports_openrouter_tools(model: str) -> bool:
    return model == "openrouter/free" or model in VERIFIED_OPENROUTER_TOOL_MODELS


@dataclass(frozen=True)
class ModelEntry:
    id: str
    provider: str
    model: str
    supports_tools: bool
    available: bool


def models() -> list[ModelEntry]:
    return [
        ModelEntry(
            id="deepseek",
            provider="deepseek",
            model=settings.deepseek_model or settings.openai_model,
            supports_tools=True,
            available=bool(settings.deepseek_api_key or settings.openai_api_key),
        ),
        ModelEntry(
            id="openrouter/free",
            provider="openrouter",
            model=settings.openrouter_model,
            supports_tools=_supports_openrouter_tools(settings.openrouter_model),
            available=bool(settings.openrouter_api_key),
        ),
        ModelEntry(
            id="openrouter/fixed",
            provider="openrouter",
            model=settings.openrouter_fixed_model,
            supports_tools=_supports_openrouter_tools(settings.openrouter_fixed_model),
            available=bool(settings.openrouter_api_key and settings.openrouter_fixed_model),
        ),
    ]


def resolve_model(model_id: str | None = None) -> ModelEntry:
    default_provider = settings.llm_provider.strip().lower()
    if model_id is None and default_provider not in {"deepseek", "openrouter"}:
        raise RuntimeError(f"Unsupported LLM provider: {settings.llm_provider}")
    selected = model_id or ("openrouter/free" if default_provider == "openrouter" else "deepseek")
    model = next((item for item in models() if item.id == selected), None)
    if model is None:
        raise RuntimeError(f"Unknown model_id: {selected}")
    return model


def get_model(model_id: str | None = None) -> ModelEntry:
    model = resolve_model(model_id)
    if not model.available:
        raise RuntimeError(f"Model {model.id} is unavailable: its provider API key is not configured")
    return model
