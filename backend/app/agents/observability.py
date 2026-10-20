"""Small per-run measurements. No prompts, arguments, results, or credentials."""
from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict

from app.providers.base import LLMProvider, LLMResponse, LLMStreamEvent


class RunObservation:
    def __init__(self, started: float | None = None, clock: Callable[[], float] | None = None):
        self.clock = clock or time.monotonic
        self.started = self.clock() if started is None else started
        self.finished: float | None = None
        self.ttft_ms: float | None = None
        self.stage = "setup"
        self.failure_stage: str | None = None
        self.failure_type: str | None = None
        self.calls: list[dict] = []
        self.tools: list[dict] = []

    @contextmanager
    def _span(self, records: list[dict], stage: str, **identity):
        self.stage = stage
        started = self.clock()
        record = {**identity, "stage": stage, "status": "running", "duration_ms": None, "error_type": None}
        records.append(record)
        try:
            yield record
            record["status"] = "completed"
        except BaseException as exc:
            record["status"] = "cancelled" if isinstance(exc, GeneratorExit) or type(exc).__name__ == "AgentCancelled" else "failed"
            record["error_type"] = type(exc).__name__
            raise
        finally:
            record["duration_ms"] = round((self.clock() - started) * 1000, 3)

    def complete(self, provider: LLMProvider, messages, *, stage: str, **kwargs) -> LLMResponse:
        with self._span(self.calls, stage, index=len(self.calls) + 1, usage=None) as call:
            response = provider.complete(messages, **kwargs)
            call.update(usage=asdict(response.usage) if response.usage else None,
                        provider=response.provider, model=response.model)
            return response

    def stream(self, provider: LLMProvider, messages, *, stage: str, **kwargs) -> Iterator[LLMStreamEvent]:
        with self._span(self.calls, stage, index=len(self.calls) + 1, usage=None) as call:
            stream = provider.stream(messages, **kwargs)
            try:
                for event in stream:
                    if event.type == "usage":
                        call["usage"] = asdict(event.usage) if event.usage else None
                    elif event.type == "done":
                        call.update(provider=event.provider, model=event.model)
                    yield event
            finally:
                close = getattr(stream, "close", None)
                if close:
                    close()

    def tool(self, step_index: int, name: str):
        return self._span(self.tools, "tool", step_index=step_index, name=name)

    def visible_text(self, content: str) -> None:
        if self.ttft_ms is None and content.strip():
            self.ttft_ms = round((self.clock() - self.started) * 1000, 3)

    def fail(self, stage: str, error_type: str) -> None:
        self.failure_stage, self.failure_type = stage, error_type

    def snapshot(self, budget_tokens: int, *, final: bool = False) -> dict:
        if final and self.finished is None:
            self.finished = self.clock()
        duration = round(((self.finished if self.finished is not None else self.clock()) - self.started) * 1000, 3)
        calls = [dict(call) for call in self.calls]
        usage = None
        if calls and all(call.get("usage") is not None for call in calls):
            usage = {key: sum(call["usage"][key] for call in calls)
                     for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
        return {
            "version": 1,
            "duration_ms": duration,
            "ttft_ms": self.ttft_ms,
            "model_call_count": len(calls),
            "model_duration_ms": round(sum(call["duration_ms"] or 0 for call in calls), 3),
            "tool_duration_ms": round(sum(tool["duration_ms"] or 0 for tool in self.tools), 3),
            "model_calls": calls,
            "tools": [dict(tool) for tool in self.tools],
            "usage": usage,
            "cost_usd": None,
            "budget_tokens": budget_tokens,
            "budget_tokens_estimated": any(call.get("usage") is None for call in calls),
            "failure_stage": self.failure_stage,
            "failure_type": self.failure_type,
            "finished": self.finished is not None,
        }
