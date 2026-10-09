from __future__ import annotations

import logging
from typing import Any, Iterator

from openai import OpenAI

from app.providers.base import LLMResponse, LLMStreamEvent, LLMUsage, ProviderToolCall
from app.providers.text_tool_calls import TextToolCallFilter


logger = logging.getLogger(__name__)


class DeepSeekProvider:
    def __init__(self, api_key: str, base_url: str, model: str, provider_name: str = "deepseek") -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._provider_name = provider_name

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        request: dict[str, Any] = {"model": self._model, "messages": messages, "tools": tools}
        if max_tokens is not None:
            request["max_tokens"] = max_tokens
        response = self._client.chat.completions.create(**request)
        message = response.choices[0].message
        tool_calls = tuple(
            ProviderToolCall(
                id=tool_call.id,
                name=tool_call.function.name,
                arguments=tool_call.function.arguments or "{}",
            )
            for tool_call in (message.tool_calls or [])
        )
        text_filter = TextToolCallFilter(tools)
        normalized = text_filter.feed(message.content or "") + text_filter.finish()
        text_tool_calls = tuple(item for item in normalized if isinstance(item, ProviderToolCall))
        raw_usage = getattr(response, "usage", None)
        usage_values = (
            getattr(raw_usage, "prompt_tokens", None),
            getattr(raw_usage, "completion_tokens", None),
            getattr(raw_usage, "total_tokens", None),
        )
        usage = (
            LLMUsage(*map(int, usage_values))
            if raw_usage is not None and all(value is not None for value in usage_values)
            else None
        )
        actual_model = getattr(response, "model", None) or self._model
        logger.info(
            "llm response provider=%s requested_model=%s actual_model=%s",
            self._provider_name, self._model, actual_model,
        )
        return LLMResponse(
            content="".join(item for item in normalized if isinstance(item, str)),
            tool_calls=tool_calls or text_tool_calls,
            model=actual_model,
            provider=self._provider_name,
            usage=usage,
        )

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[LLMStreamEvent]:
        request: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "tools": tools,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if max_tokens is not None:
            request["max_tokens"] = max_tokens
        response = self._client.chat.completions.create(**request)
        pending_tools: dict[int, dict[str, str]] = {}
        text_filter = TextToolCallFilter(tools)
        model = self._model
        try:
            for chunk in response:
                model = getattr(chunk, "model", None) or model
                raw_usage = getattr(chunk, "usage", None)
                if raw_usage is not None:
                    values = (
                        getattr(raw_usage, "prompt_tokens", None),
                        getattr(raw_usage, "completion_tokens", None),
                        getattr(raw_usage, "total_tokens", None),
                    )
                    if all(value is not None for value in values):
                        yield LLMStreamEvent("usage", usage=LLMUsage(*map(int, values)))
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    for item in text_filter.feed(delta.content):
                        yield LLMStreamEvent("tool_call", tool_call=item) if isinstance(item, ProviderToolCall) else LLMStreamEvent("message", content=item)
                for fragment in delta.tool_calls or []:
                    item = pending_tools.setdefault(fragment.index, {"id": "", "name": "", "arguments": ""})
                    item["id"] += fragment.id or ""
                    if fragment.function:
                        item["name"] += fragment.function.name or ""
                        item["arguments"] += fragment.function.arguments or ""
            for item in text_filter.finish():
                yield LLMStreamEvent("tool_call", tool_call=item) if isinstance(item, ProviderToolCall) else LLMStreamEvent("message", content=item)
            for index in sorted(pending_tools):
                item = pending_tools[index]
                yield LLMStreamEvent(
                    "tool_call",
                    tool_call=ProviderToolCall(item["id"], item["name"], item["arguments"] or "{}"),
                )
            logger.info(
                "llm stream complete provider=%s requested_model=%s actual_model=%s",
                self._provider_name, self._model, model,
            )
            yield LLMStreamEvent("done", model=model, provider=self._provider_name)
        finally:
            response.close()
