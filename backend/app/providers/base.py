from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Literal, Protocol


@dataclass(frozen=True)
class ProviderToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    def __add__(self, other: "LLMUsage") -> "LLMUsage":
        return LLMUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass(frozen=True)
class LLMResponse:
    content: str
    tool_calls: tuple[ProviderToolCall, ...] = ()
    model: str | None = None
    provider: str | None = None
    usage: LLMUsage | None = None


@dataclass(frozen=True)
class LLMStreamEvent:
    type: Literal["message", "tool_call", "usage", "done"]
    content: str = ""
    tool_call: ProviderToolCall | None = None
    usage: LLMUsage | None = None
    model: str | None = None
    provider: str | None = None


class LLMProvider(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[LLMStreamEvent]: ...
