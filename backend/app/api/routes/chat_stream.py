from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.routes.chat import (
    _build_system_prompt,
    _extract_filename_from_query,
    _needs_full_document,
    _should_use_rag,
    relevant_tool_specs,
    resolve_workspace_request,
)
from app.core.config import settings
from app.core.database import save_chat_turn
from app.models.chat import ChartArtifact, ChatRequest, CitationSource, ToolCallLog
from app.providers.base import LLMStreamEvent, LLMUsage, ProviderToolCall
from app.providers.factory import create_llm_provider
from app.providers.registry import resolve_model
from app.rag.service import get_rag_service
from app.tools.registry import execute_tool_call, get_enabled_tool_specs
from app.tools.web_search import web_citations

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _events(req: ChatRequest) -> Iterator[str]:
    session_id = req.session_id or str(uuid4())
    latest_user = next((item for item in reversed(req.messages) if item.role == "user"), None)
    try:
        req = resolve_workspace_request(req)
        provider = create_llm_provider(req.model_id)
        specs = relevant_tool_specs(req, get_enabled_tool_specs(req.settings, req.workspace_id))
        if specs and not resolve_model(req.model_id).supports_tools:
            raise RuntimeError(f"Model {req.model_id or 'default'} does not support Tool Calling; disable tool settings or choose another model.")
        tool_map = {item.name: item for item in specs}
        if settings.app_env == "dev":
            logger.info(
                "workspace_id=%s tool_settings.web_search=%s search_web_registered=%s",
                req.workspace_id,
                req.settings.web_search,
                "search_web" in tool_map,
            )
        tools = [item.as_openai_tool() for item in specs] or None
        messages = [
            {"role": "system", "content": _build_system_prompt(req, list(tool_map))},
            *({"role": item.role, "content": item.content} for item in req.messages),
        ]
        sources: list[CitationSource] = []
        charts: list[ChartArtifact] = []

        if _should_use_rag(req):
            query = latest_user.content if latest_user else ""
            filename = _extract_filename_from_query(query, session_id, req.workspace_id) if query else None
            try:
                rag = get_rag_service()
                chunks = (
                    rag.retrieve_all(session_id=session_id, filename=filename, **({"workspace_id": req.workspace_id} if req.workspace_id else {}))
                    if _needs_full_document(query)
                    else rag.retrieve(session_id=session_id, query=query, top_k=5, filename=filename, **({"workspace_id": req.workspace_id} if req.workspace_id else {}))
                )
            except Exception as exc:
                chunks = []
                messages.insert(1, {"role": "system", "content": f"RAG retrieval failed and will be ignored. Error: {type(exc).__name__}: {exc}"})
            if chunks:
                sources = [
                    CitationSource(
                        title=chunk.filename,
                        filename=chunk.filename,
                        document_id=chunk.document_id,
                        chunk_index=chunk.chunk_index,
                        content_preview=" ".join(chunk.content.split())[:240],
                        distance=chunk.distance,
                    )
                    for chunk in chunks
                ]
                context = [f"RAG_CONTEXT: Retrieved information from uploaded files (session: {session_id}):", ""]
                for index, chunk in enumerate(chunks, 1):
                    context.extend([
                        f"[Source {index}] filename={chunk.filename}; document_id={chunk.document_id}; chunk_index={chunk.chunk_index}",
                        chunk.content,
                        "",
                    ])
                context.append(
                    "Use the retrieved chunks to answer. The source may contain PDF extraction artifacts; "
                    "do not invent missing content. Cite only numbered sources above using [1], [2], etc.; "
                    "never invent a source number. If information is absent, say so."
                )
                messages.insert(1, {"role": "system", "content": "\n".join(context)})

        content_parts: list[str] = []
        usage: LLMUsage | None = None
        provider_name: str | None = None
        model: str | None = None
        one_shot_results: dict[str, object] = {}
        for tool_round in range(5):
            round_parts: list[str] = []
            tool_calls: list[ProviderToolCall] = []
            round_usage: LLMUsage | None = None
            for event in provider.stream(messages, tools):
                if event.type == "message":
                    if tools:
                        round_parts.append(event.content)
                    else:
                        content_parts.append(event.content)
                        yield _sse("message", {"content": event.content})
                elif event.type == "tool_call" and event.tool_call:
                    tool_calls.append(event.tool_call)
                elif event.type == "usage":
                    round_usage = event.usage
                elif event.type == "done":
                    provider_name, model = event.provider, event.model
            usage = (
                round_usage if tool_round == 0
                else usage + round_usage if usage is not None and round_usage is not None
                else None
            )

            if not tool_calls:
                for part in round_parts:
                    content_parts.append(part)
                    yield _sse("message", {"content": part})
                break
            if tool_round == 4:
                raise RuntimeError("Model exceeded the maximum of 4 tool-call rounds")

            messages.append({
                "role": "assistant",
                "content": "".join(round_parts),
                "tool_calls": [
                    {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}}
                    for call in tool_calls
                ],
            })
            for call in tool_calls:
                log = ToolCallLog(name=call.name)
                try:
                    parsed = json.loads(call.arguments or "{}")
                    log.input = parsed if isinstance(parsed, dict) else None
                    reused = call.name != "analyze_data" and call.name in one_shot_results
                    result = one_shot_results[call.name] if reused else execute_tool_call(tool_map, call.name, call.arguments)
                    if call.name != "analyze_data" and not reused:
                        one_shot_results[call.name] = result
                    if call.name == "search_web" and isinstance(result, dict) and not reused:
                        sources.extend(web_citations(result))
                    if call.name == "analyze_data" and isinstance(result, dict) and result.get("type") == "chart":
                        charts.append(ChartArtifact(url=result["url"], title=result["title"]))
                    log.output_preview = json.dumps(result, ensure_ascii=False)[:2000]
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
                    note = result.get("note") if isinstance(result, dict) else None
                    if isinstance(note, str) and ("stub" in note.lower() or "not implemented" in note.lower()):
                        messages.append({"role": "system", "content": f"TOOL_NOTICE: {call.name} returned a stub/not-implemented result. Briefly disclose this; do not claim fresh results."})
                except Exception as exc:
                    log.error = f"{type(exc).__name__}: {exc}"
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps({"error": log.error, "tool": call.name})})
                yield _sse("tool_call", log.model_dump())

            one_shot_tools = {call.name for call in tool_calls if call.name != "analyze_data"}
            if one_shot_tools:
                specs = [spec for spec in specs if spec.name not in one_shot_tools]
                tools = [spec.as_openai_tool() for spec in specs] or None

        for source in sources:
            yield _sse("source", source.model_dump())
        for chart in charts:
            yield _sse("chart", chart.model_dump())
        yield _sse("usage", usage.__dict__ if usage else None)

        # Commit only after all provider streams finish; failure/cancellation never stores a partial answer.
        if latest_user:
            save_chat_turn(
                session_id=session_id,
                user_content=latest_user.content,
                assistant_content="".join(content_parts).strip() or "(empty response)",
                provider=provider_name,
                model=model,
                usage=usage,
                **({"workspace_id": req.workspace_id} if req.workspace_id else {}),
            )
        yield _sse("done", {"session_id": session_id})
    except Exception as exc:
        yield _sse("error", {"message": f"Streaming failed: {type(exc).__name__}: {exc}"})


@router.post("/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        _events(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
