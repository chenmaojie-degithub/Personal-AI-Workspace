from __future__ import annotations

import unittest
from unittest.mock import patch

from app.core.config import Settings
from app.rag import embeddings


class EmbeddingProviderConfigTests(unittest.TestCase):
    def test_deepseek_chat_key_is_not_reused_for_openai_embeddings(self) -> None:
        test_settings = Settings(
            _env_file=None,
            openai_api_key="deepseek-test-key",
            openai_base_url="https://api.deepseek.com",
            embedding_provider="openai",
            openai_embedding_api_key=None,
        )

        with patch.object(embeddings, "settings", test_settings), patch.object(
            embeddings, "OpenAI"
        ) as openai:
            self.assertIsNone(embeddings.create_embedding_provider())
            openai.assert_not_called()

    def test_default_openai_chat_key_remains_backward_compatible(self) -> None:
        test_settings = Settings(
            _env_file=None,
            openai_api_key="openai-test-key",
            openai_base_url=None,
            embedding_provider="openai",
        )

        with patch.object(embeddings, "settings", test_settings), patch.object(
            embeddings, "OpenAI"
        ) as openai:
            self.assertIsNotNone(embeddings.create_embedding_provider())
            openai.assert_called_once_with(api_key="openai-test-key", base_url=None)

    def test_local_provider_uses_configured_model_and_cache(self) -> None:
        test_settings = Settings(
            _env_file=None,
            embedding_provider="local",
            local_embedding_model="BAAI/bge-small-zh-v1.5",
            local_embedding_cache_dir="./models",
        )

        with patch.object(embeddings, "settings", test_settings), patch.object(
            embeddings, "FastEmbedEmbeddingProvider"
        ) as local_provider:
            embeddings.create_embedding_provider()
            local_provider.assert_called_once_with(
                model="BAAI/bge-small-zh-v1.5",
                cache_dir="./models",
            )


if __name__ == "__main__":
    unittest.main()
