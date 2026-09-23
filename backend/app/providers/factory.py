from __future__ import annotations

from app.core.config import settings
from app.providers.base import LLMProvider
from app.providers.deepseek import DeepSeekProvider
from app.providers.openrouter import OpenRouterProvider
from app.providers.registry import get_model


def create_llm_provider(model_id: str | None = None) -> LLMProvider:
    selected = get_model(model_id)
    if selected.provider == "openrouter":
        return OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            model=selected.model,
        )

    api_key = settings.deepseek_api_key or settings.openai_api_key
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY is not configured "
            "(legacy OPENAI_API_KEY is also supported)."
        )

    return DeepSeekProvider(
        api_key=api_key,
        base_url=settings.deepseek_base_url
        or settings.openai_base_url
        or "https://api.deepseek.com",
        model=selected.model,
    )
