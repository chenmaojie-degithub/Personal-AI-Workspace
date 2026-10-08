from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from app.models.chat import ChatSettings
from app.services.data_analysis import CHART_TYPES, OPERATIONS
from app.tools.data_analysis import analyze_data
from app.tools.image_generation import generate_image
from app.tools.knowledge import read_document, search_knowledge
from app.tools.web_search import web_search


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters_schema: dict[str, Any]
    handler: Callable[..., Any]

    def as_openai_tool(self) -> dict[str, Any]:
        # OpenAI "tools" format: {"type": "function", "function": { ... }}
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }


def get_enabled_tool_specs(settings: ChatSettings, workspace_id: str | None = None) -> list[ToolSpec]:
    """
    Build tool list conditionally based on settings.

    IMPORTANT: disabled tools must not be registered at all.
    """
    specs: list[ToolSpec] = []

    if settings.web_search:
        specs.append(
            ToolSpec(
                name="search_web",
                description=(
                    "Search the web for current, recent, or external information. "
                    "Use when the user's question needs information beyond model knowledge."
                ),
                parameters_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
                handler=lambda query: web_search(query=query),
            )
        )

    if settings.image_generation:
        specs.append(
            ToolSpec(
                name="generate_image",
                description=(
                    "Image generation (STUB): currently returns an empty image list and a note (not implemented). "
                    "Be transparent with the user."
                ),
                parameters_schema={
                    "type": "object",
                    "properties": {"prompt": {"type": "string"}},
                    "required": ["prompt"],
                    "additionalProperties": False,
                },
                handler=lambda prompt: generate_image(prompt=prompt),
            )
        )

    if settings.data_analysis:
        specs.append(
            ToolSpec(
                name="analyze_data",
                description=(
                    "Safely analyze an uploaded CSV or XLSX file in the current Workspace. "
                    "Use only a listed file_id; calculations use a fixed backend whitelist."
                ),
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "operation": {"type": "string", "enum": sorted(OPERATIONS)},
                        "column": {"type": ["string", "null"]},
                        "group_by": {"type": ["string", "null"]},
                        "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 100},
                        "chart_type": {"type": ["string", "null"], "enum": [*sorted(CHART_TYPES), None]},
                        "x_column": {"type": ["string", "null"]},
                        "y_column": {"type": ["string", "null"]},
                    },
                    "required": ["file_id", "operation"],
                    "additionalProperties": False,
                },
                handler=lambda **arguments: analyze_data(workspace_id, **arguments),
            )
        )

    return specs


def get_agent_tool_specs(
    settings: ChatSettings,
    session_id: str,
    workspace_id: str | None = None,
    document_ids: list[str] | None = None,
) -> list[ToolSpec]:
    specs = get_enabled_tool_specs(settings, workspace_id)
    allowed_documents = set(document_ids) if document_ids else None

    def ensure_allowed(document_id: str | None) -> None:
        if allowed_documents is not None and document_id not in allowed_documents:
            raise ValueError("document_id must be one of the documents associated with this task")

    def scoped_search(**arguments: Any) -> Any:
        ensure_allowed(arguments.get("document_id"))
        return search_knowledge(session_id, workspace_id, **arguments)

    def scoped_read(**arguments: Any) -> Any:
        ensure_allowed(arguments.get("document_id"))
        return read_document(session_id, workspace_id, **arguments)

    specs.extend([
        ToolSpec(
            name="search_knowledge",
            description="Search indexed documents in the current Workspace for relevant evidence.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "document_id": {"type": ["string", "null"]},
                    "top_k": {"type": ["integer", "null"], "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=scoped_search,
        ),
        ToolSpec(
            name="read_document",
            description=(
                "Read the next ordered segment of an indexed document in the current Workspace. "
                "Continue with next_cursor until complete when whole-document coverage is required."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "cursor": {"type": ["integer", "null"], "minimum": 0},
                    "max_chars": {"type": ["integer", "null"], "minimum": 500, "maximum": 12000},
                },
                "required": ["document_id"],
                "additionalProperties": False,
            },
            handler=scoped_read,
        ),
    ])
    return specs


def execute_tool_call(tool_map: dict[str, ToolSpec], name: str, arguments_json: str) -> Any:
    """
    Execute a tool call safely.
    """
    if name not in tool_map:
        raise ValueError(f"Tool not found or not enabled: {name}")

    args = json.loads(arguments_json or "{}")
    if not isinstance(args, dict):
        raise ValueError("Tool arguments must be a JSON object")
    _validate_arguments(tool_map[name].parameters_schema, args)

    return tool_map[name].handler(**args)


def _validate_arguments(schema: dict[str, Any], args: dict[str, Any]) -> None:
    properties = schema.get("properties", {})
    unknown = set(args) - set(properties)
    if unknown and schema.get("additionalProperties") is False:
        raise ValueError(f"Unexpected tool arguments: {', '.join(sorted(unknown))}")
    missing = set(schema.get("required", [])) - set(args)
    if missing:
        raise ValueError(f"Missing tool arguments: {', '.join(sorted(missing))}")
    for name, value in args.items():
        rule = properties.get(name, {})
        allowed = rule.get("type", [])
        allowed = [allowed] if isinstance(allowed, str) else allowed
        valid = (
            (value is None and "null" in allowed)
            or (isinstance(value, str) and "string" in allowed)
            or (isinstance(value, int) and not isinstance(value, bool) and "integer" in allowed)
        )
        if allowed and not valid:
            raise ValueError(f"Tool argument {name} has an invalid type")
        if "enum" in rule and value not in rule["enum"]:
            raise ValueError(f"Tool argument {name} has an invalid value")
        if isinstance(value, int) and not isinstance(value, bool):
            if "minimum" in rule and value < rule["minimum"]:
                raise ValueError(f"Tool argument {name} is below the minimum")
            if "maximum" in rule and value > rule["maximum"]:
                raise ValueError(f"Tool argument {name} exceeds the maximum")
