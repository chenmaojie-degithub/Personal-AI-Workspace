"""Fixed offline evaluation, using real routing/validation and existing test doubles.

Set PAW_AGENT_EVAL_OUTPUT to explicitly export this suite's machine-readable results.
Normal full regression does not overwrite the checked-in evaluation report.
"""
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from types import SimpleNamespace

import pytest

from app.agents.orchestrator import cancel_agent_run
from app.api.routes.chat_stream import _routed_events
from app.core import database
from app.models.chat import ChatRequest
from app.providers.base import LLMStreamEvent, LLMUsage, ProviderToolCall
from app.providers.text_tool_calls import TextToolCallError
from app.tests.test_agent_orchestrator import Provider, response
from app.tests.test_citations import catalog
from app.tools.registry import execute_tool_call

SPEC = Path(__file__).with_name("fixtures") / "agent_evaluation_v1.json"
CASES = json.loads(SPEC.read_text(encoding="utf-8"))["cases"]
WEB = [{"title": name.title(), "url": f"https://example.test/{name}", "snippet": f"Synthetic {name} evidence"}
       for name in ("alpha", "beta", "gamma")]
KNOWLEDGE = {"type": "knowledge_search", "results": [{
    "document_id": "local-doc", "filename": "synthetic.txt", "chunk_index": 0,
    "content": "Synthetic local evidence", "page_number": 1,
}]}


def source_key(source):
    return ("web:" + str(source.get("url")) if source["type"] == "web" else
            f"knowledge:{source.get('document_id')}:{source.get('chunk_index')}")


def citation_score(content, sources, expected_catalog):
    references = [int(n) for n in re.findall(r"【(\d+)】", content)]
    indexed = {source.get("citation_id"): source_key(source) for source in sources}
    valid = sum(0 < n <= len(expected_catalog) and indexed.get(n) == expected_catalog[n - 1] for n in references)
    catalog_matches = (
        [source_key(source) for source in sources] == expected_catalog
        and [source.get("citation_id") for source in sources] == list(range(1, len(sources) + 1))
        and len(indexed) == len(sources)
        and len(set(indexed.values())) == len(sources)
    )
    return {"references": references, "valid_references": valid, "reference_count": len(references),
            "accuracy": valid / len(references) if references else None, "catalog_matches": catalog_matches}


def repeated_calls(attempts):
    counts = Counter((item["name"], json.dumps(item["arguments"], sort_keys=True)) for item in attempts)
    return sum(count - 1 for count in counts.values())


def summarize(rows):
    citations = sum(row["citation_reference_count"] for row in rows)
    valid = sum(row["valid_citation_references"] for row in rows)
    known = [row["usage"] for row in rows if row["usage"] is not None]
    subtotal = {key: sum(usage[key] for usage in known) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
    return {
        "scenario_count": len(rows), "passed": sum(row["passed"] for row in rows),
        "scenario_pass_rate": sum(row["passed"] for row in rows) / len(rows) if rows else None,
        "tool_match_rate": sum(row["checks"]["tools_match"] for row in rows) / len(rows) if rows else None,
        "forbidden_tool_executions": sum(row["forbidden_tool_executions"] for row in rows),
        "rejected_tool_attempts": sum(row["rejected_tool_attempts"] for row in rows),
        "repeated_tool_attempts": sum(row["repeated_tool_attempts"] for row in rows),
        "model_call_count": sum(row["model_call_count"] for row in rows),
        "citation_reference_count": citations, "valid_citation_references": valid,
        "citation_structure_accuracy": valid / citations if citations else None,
        "usage": subtotal if rows and len(known) == len(rows) else None,
        "known_usage_subtotal": subtotal if known else None,
        "unknown_usage_scenarios": len(rows) - len(known),
        "usage_origin": "scripted Mock Provider, not real service billing",
    }


class EvaluationProvider(Provider):
    """Reuse the existing queued Provider and usage helper, adding catalog-based deltas."""
    def __init__(self, case):
        scripted = []
        if case["expected_route"] == "agent":
            scripted.append(response('{"steps":["Find evidence","Check evidence","Answer"]}'))
            for index, action in enumerate(case["actions"]):
                if "parse_error" in action:
                    scripted.append(TextToolCallError(action["parse_error"]))
                else:
                    call = ProviderToolCall(f"call-{index}", action["name"], json.dumps(action["arguments"]))
                    scripted.append(response("", (call,)))
            scripted.append(response("FINAL_READY"))
        super().__init__(*scripted)
        self.case = case
        self.stream_count = 0

    def complete(self, messages, tools=None, max_tokens=None):
        if self.responses and isinstance(self.responses[0], Exception):
            self.tools.append(tools)
            self.max_tokens.append(max_tokens)
            raise self.responses.pop(0)
        return super().complete(messages, tools, max_tokens)

    def stream(self, messages, tools=None, max_tokens=None):
        self.stream_count += 1
        entries = {source_key(entry): entry for entry in catalog(messages)}
        text = "A variable holds a value." if self.case["expected_route"] == "chat" else "Evaluation answer."
        for key in self.case["answer_sources"]:
            text += " " + entries[key]["marker"]
        if self.case.get("invalid_citation"):
            text += " 【999】"
        for index in range(0, len(text), 8):
            yield LLMStreamEvent("message", content=text[index:index + 8])
        yield LLMStreamEvent("usage", usage=LLMUsage(5, 1, 6))
        yield LLMStreamEvent("done", model="offline-evaluation", provider="mock")


@pytest.fixture(scope="session")
def evaluation_rows():
    rows = []
    yield rows
    output = os.environ.get("PAW_AGENT_EVAL_OUTPUT")
    if not output:
        return
    expected_ids = {case["id"] for case in CASES}
    assert {row["id"] for row in rows} == expected_ids, "Export requires the complete fixed suite"
    root = Path(__file__).resolve().parents[3]
    paths = [SPEC, Path(__file__), *(root / "backend/app" / name for name in (
        "agents/orchestrator.py", "agents/observability.py", "services/citations.py",
        "tools/registry.py", "api/routes/chat_stream.py",
    ))]
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = None
    report = {
        "schema_version": 1, "suite_version": 1, "engine_revision_at_run": revision,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "offline scripted providers and synthetic evidence; no LLM judge",
        "source_sha256": {str(path.relative_to(root)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
        "summary": summarize(rows), "scenarios": sorted(rows, key=lambda row: [case["id"] for case in CASES].index(row["id"])),
    }
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_fixed_agent_evaluation(case, tmp_path, monkeypatch, evaluation_rows):
    monkeypatch.setattr(database.settings, "database_url", "sqlite:///" + (tmp_path / "evaluation.db").as_posix())
    monkeypatch.setattr(database.settings, "storage_dir", str(tmp_path / "storage"))
    monkeypatch.setattr(database.settings, "chroma_persist_dir", str(tmp_path / "chroma"))
    if case.get("token_budget"):
        monkeypatch.setattr(database.settings, "agent_token_budget", case["token_budget"])
    workspace = database.create_workspace("Synthetic evaluation workspace")
    database.update_workspace(workspace["id"], {"tool_settings": {"web_search": case.get("web_search", True)}})
    document_ids = []
    if case.get("foreign_document"):
        foreign = database.create_workspace("Synthetic foreign workspace")
        doc = database.create_document_record(filename="foreign.txt", content_type="text/plain", byte_size=10,
                                              content_sha256="a" * 64, workspace_id=foreign["id"])
        document_ids = [doc["id"]]
    request = ChatRequest(session_id="evaluation-session", workspace_id=workspace["id"], document_ids=document_ids,
                          messages=[{"role": "user", "content": case["goal"]}])
    provider = EvaluationProvider(case)
    for module in ("app.agents.orchestrator", "app.api.routes.chat_stream"):
        monkeypatch.setattr(module + ".create_llm_provider", lambda *args: provider)
        monkeypatch.setattr(module + ".resolve_model", lambda *args: SimpleNamespace(supports_tools=True))
    executions, attempts = [], []
    permitted = {"search_knowledge", "read_document"}
    if case.get("web_search", True):
        permitted.add("search_web")

    def web_search(query):
        executions.append({"name": "search_web", "scope_ok": True})
        if case.get("web_error_once"):
            raise RuntimeError("Synthetic search unavailable")
        return {"results": [*WEB, WEB[0]]}  # Also checks duplicate URLs within one result.

    def knowledge(session_id, workspace_id, **kwargs):
        executions.append({"name": "search_knowledge", "scope_ok": workspace_id == workspace["id"]})
        return KNOWLEDGE

    def read(session_id, workspace_id, **kwargs):
        executions.append({"name": "read_document", "scope_ok": workspace_id == workspace["id"]})
        raise AssertionError("No scenario permits reading the foreign document")

    monkeypatch.setattr("app.tools.registry.web_search", web_search)
    monkeypatch.setattr("app.tools.registry.search_knowledge", knowledge)
    monkeypatch.setattr("app.tools.registry.read_document", read)
    def forbidden_handler(name):
        def handler(*args, **kwargs):
            executions.append({"name": name, "scope_ok": True})
            raise RuntimeError("Unexpected synthetic tool execution")
        return handler
    monkeypatch.setattr("app.tools.registry.analyze_data", forbidden_handler("analyze_data"))
    monkeypatch.setattr("app.tools.registry.generate_image", forbidden_handler("generate_image"))

    def traced_execute(tool_map, name, arguments_json):
        before = len(executions)
        attempt = {"name": name, "arguments": json.loads(arguments_json), "rejected": False}
        attempts.append(attempt)
        try:
            return execute_tool_call(tool_map, name, arguments_json)  # Real validation/dispatch.
        except Exception:
            attempt["rejected"] = len(executions) == before
            raise

    for module in ("app.agents.orchestrator", "app.api.routes.chat_stream"):
        monkeypatch.setattr(module + ".execute_tool_call", traced_execute)
    events = []
    cancelled = False
    started = time.monotonic()
    for block in _routed_events(request):
        kind = block.splitlines()[0][7:]
        data = json.loads(block.split("data: ", 1)[1])
        events.append((kind, data))
        if case["id"] == "cancel" and kind == "message" and data["content"].strip() and not cancelled:
            run_id = next(data["run_id"] for event, data in events if event == "agent_run")
            cancel_agent_run(run_id, workspace["id"])
            cancelled = True
    elapsed_ms = (time.monotonic() - started) * 1000
    run_ids = [data["run_id"] for event, data in events if event == "agent_run"]
    run = database.get_agent_run(run_ids[0], workspace["id"]) if run_ids else None
    metrics = run["metrics"] if run else None
    status = run["status"] if run else "completed" if events[-1][0] == "done" else "failed"
    content = "".join(data["content"] for kind, data in events if kind == "message")
    sources = [data for kind, data in events if kind == "source"]
    citation = citation_score(content, sources, case["expected_catalog"])
    executed = [execution["name"] for execution in executions]
    forbidden = sum(execution["name"] not in permitted or not execution["scope_ok"] for execution in executions)
    rejected = sum(attempt["rejected"] for attempt in attempts)
    model_count = len(provider.tools) + provider.stream_count
    usage_events = [data for kind, data in events if kind == "usage"]
    usage = metrics["usage"] if metrics else usage_events[-1] if usage_events else None
    history = database.list_messages(request.session_id, workspace["id"])
    referenced = {source_key(source) for source in sources if source["citation_id"] in citation["references"]}
    failure_type = metrics["failure_type"] if metrics else None
    checks = {
        "route_matches": bool(run) == (case["expected_route"] == "agent"),
        "status_matches": status == case["expected_status"],
        "tools_match": executed == case["expected_tools"],
        "no_forbidden_execution": forbidden == 0,
        "rejected_attempts_match": rejected == case["expected_rejected_attempts"],
        "repeats_match": repeated_calls(attempts) == case["expected_repeated_calls"],
        "model_calls_match": model_count == case["expected_model_calls"],
        "observation_matches_provider": metrics is None or metrics["model_call_count"] == model_count,
        "source_catalog_matches": citation["catalog_matches"],
        "citation_references_valid": citation["valid_references"] == citation["reference_count"],
        "required_citations_present": set(case["required_citations"]).issubset(referenced),
        "failure_type_matches": failure_type == case.get("expected_failure_type"),
        "control_markers_hidden": "[[cite:" not in content and "<|tool_call" not in content and "【999】" not in content,
        "completed_chat_saved_once": (len(history) == 2 and history[-1]["content"] == content) if status == "completed" else not history,
        "done_matches_completion": any(kind == "done" for kind, _ in events) == (status in {"completed", "budget_exceeded"}),
        "simple_no_planner": case["expected_route"] != "chat" or (not provider.tools and provider.stream_count == 1),
    }
    # Budget exhaustion emits a deliberate terminal explanation, not an unfinished model answer.
    if status == "budget_exceeded":
        checks["completed_chat_saved_once"] = len(history) == 2 and history[-1]["content"] == content
    row = {
        "id": case["id"], "goal": case["goal"], "passed": all(checks.values()), "checks": checks,
        "expected_status": case["expected_status"], "actual_status": status,
        "expected_tools": case["expected_tools"], "actual_tools": executed,
        "forbidden_tool_executions": forbidden, "rejected_tool_attempts": rejected,
        "repeated_tool_attempts": repeated_calls(attempts), "model_call_count": model_count,
        "usage": usage, "duration_ms": metrics["duration_ms"] if metrics else round(elapsed_ms, 3),
        "duration_scope": "Agent Run monotonic" if metrics else "direct route monotonic",
        "failure_type": failure_type, "citation_reference_count": citation["reference_count"],
        "valid_citation_references": citation["valid_references"], "citation_structure_accuracy": citation["accuracy"],
        "source_catalog": [source_key(source) for source in sources],
    }
    evaluation_rows.append(row)
    assert row["passed"], {key: value for key, value in checks.items() if not value}


def test_citation_scorer_rejects_wrong_identity_even_with_existing_number():
    sources = [{"type": "web", "url": "https://example.test/beta", "citation_id": 1}]
    score = citation_score("claim 【1】", sources, ["web:https://example.test/alpha"])
    assert not score["catalog_matches"] and score["accuracy"] == 0
    assert citation_score("claim 【999】", sources, ["web:https://example.test/beta"])["accuracy"] == 0
    assert citation_score("no references", [], [])["accuracy"] is None


def test_repeat_scorer_canonicalizes_argument_key_order():
    assert repeated_calls([{"name": "tool", "arguments": {"a": 1, "b": 2}},
                           {"name": "tool", "arguments": {"b": 2, "a": 1}},
                           {"name": "tool", "arguments": {"a": 2}}]) == 1


def test_summary_does_not_report_partial_usage_as_complete():
    row = {"passed": True, "checks": {"tools_match": True}, "forbidden_tool_executions": 0,
           "rejected_tool_attempts": 0, "repeated_tool_attempts": 0, "model_call_count": 1,
           "citation_reference_count": 0, "valid_citation_references": 0, "usage": None}
    result = summarize([row, {**row, "usage": asdict(LLMUsage(8, 2, 10))}])
    assert result["usage"] is None and result["known_usage_subtotal"]["total_tokens"] == 10
    assert result["unknown_usage_scenarios"] == 1 and result["citation_structure_accuracy"] is None
