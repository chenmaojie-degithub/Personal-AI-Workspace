from __future__ import annotations

from app.providers.deepseek import DeepSeekProvider


class OpenRouterProvider(DeepSeekProvider):
    """OpenRouter uses the same OpenAI-compatible chat and streaming protocol."""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        super().__init__(api_key, base_url, model, provider_name="openrouter")
