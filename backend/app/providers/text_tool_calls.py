from __future__ import annotations

import ast
import json
from uuid import uuid4

from app.providers.base import ProviderToolCall

START = "<|tool_call_start|>"
END = "<|tool_call_end|>"


def _prefix_tail(text: str, marker: str) -> int:
    return next((size for size in range(min(len(text), len(marker) - 1), 0, -1) if text.endswith(marker[:size])), 0)


def _parse_call(body: str, tools: list[dict] | None) -> ProviderToolCall:
    try:
        expression = ast.parse(body.strip(), mode="eval").body
        if isinstance(expression, ast.List) and len(expression.elts) == 1:
            expression = expression.elts[0]
        if not isinstance(expression, ast.Call) or not isinstance(expression.func, ast.Name) or expression.args:
            raise ValueError
        name = "search_web" if expression.func.id == "web_search" else expression.func.id
        enabled = {tool["function"]["name"]: tool["function"] for tool in tools or []}
        if name not in enabled:
            raise ValueError
        arguments = {
            keyword.arg: ast.literal_eval(keyword.value)
            for keyword in expression.keywords
            if keyword.arg is not None
        }
        if len(arguments) != len(expression.keywords):
            raise ValueError
        if name == "search_web":
            query = arguments.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError
            # Some models emit legacy provider hints. V1 deliberately exposes only query.
            arguments = {"query": query}
        else:
            schema = enabled[name].get("parameters", {})
            properties = schema.get("properties", {})
            if not set(arguments).issubset(properties) or not set(schema.get("required", [])).issubset(arguments):
                raise ValueError
    except (SyntaxError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("Model returned an invalid text tool call") from exc
    return ProviderToolCall(f"call_text_{uuid4().hex}", name, json.dumps(arguments))


class TextToolCallFilter:
    """Hold partial control markers so streamed text never exposes them."""

    def __init__(self, tools: list[dict] | None) -> None:
        self.tools = tools
        self.pending = ""
        self.call = ""
        self.in_call = False

    def feed(self, content: str) -> list[str | ProviderToolCall]:
        self.pending += content
        output: list[str | ProviderToolCall] = []
        while self.pending:
            if self.in_call:
                end = self.pending.find(END)
                if end >= 0:
                    self.call += self.pending[:end]
                    output.append(_parse_call(self.call, self.tools))
                    self.call = ""
                    self.pending = self.pending[end + len(END):]
                    self.in_call = False
                    continue
                keep = _prefix_tail(self.pending, END)
                self.call += self.pending[:-keep] if keep else self.pending
                self.pending = self.pending[-keep:] if keep else ""
                if len(self.call) > 2000:
                    raise ValueError("Model returned an oversized text tool call")
            else:
                start = self.pending.find(START)
                if start >= 0:
                    if start:
                        output.append(self.pending[:start])
                    self.pending = self.pending[start + len(START):]
                    self.in_call = True
                    continue
                keep = _prefix_tail(self.pending, START)
                safe = self.pending[:-keep] if keep else self.pending
                if safe:
                    output.append(safe)
                self.pending = self.pending[-keep:] if keep else ""
            break
        return output

    def finish(self) -> list[str | ProviderToolCall]:
        if self.in_call:
            raise ValueError("Model returned an incomplete text tool call")
        remaining = self.pending
        self.pending = ""
        return [remaining] if remaining and not START.startswith(remaining) else []
