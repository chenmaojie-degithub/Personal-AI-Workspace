from __future__ import annotations

from pathlib import Path
from typing import Protocol

from openai import OpenAI

from app.core.config import settings


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddingProvider:
    def __init__(self, api_key: str, base_url: str | None, model: str) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url or None)
        self._model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in response.data]


class FastEmbedEmbeddingProvider:
    def __init__(self, model: str, cache_dir: str) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(
            model_name=model,
            cache_dir=str(Path(cache_dir).resolve()),
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]


def create_embedding_provider() -> EmbeddingProvider | None:
    provider = settings.embedding_provider.strip().lower()
    if provider in {"", "none", "disabled"}:
        return None
    if provider == "local":
        return FastEmbedEmbeddingProvider(
            model=settings.local_embedding_model,
            cache_dir=settings.local_embedding_cache_dir,
        )
    if provider != "openai":
        raise RuntimeError(f"Unsupported embedding provider: {settings.embedding_provider}")

    api_key = settings.openai_embedding_api_key
    if not api_key and not settings.openai_base_url:
        # Backward compatible for the default OpenAI chat endpoint only.
        api_key = settings.openai_api_key
    if not api_key:
        return None

    return OpenAIEmbeddingProvider(
        api_key=api_key,
        base_url=settings.openai_embedding_base_url,
        model=settings.openai_embedding_model,
    )
