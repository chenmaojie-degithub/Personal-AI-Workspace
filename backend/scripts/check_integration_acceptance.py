"""Real TCP/HTTP checks, only for the disposable port-18800 acceptance server."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import httpx


def frames(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    kind = None
    for line in response.iter_lines():
        if line.startswith("event: "):
            kind = line[7:]
        elif line.startswith("data: "):
            assert kind is not None
            yield kind, json.loads(line[6:])


def main(output):
    rows = []
    with httpx.Client(base_url="http://127.0.0.1:18800", timeout=30, trust_env=False) as client:
        state = client.get("/__acceptance/state").json()
        assert state["marker"] == "paw-integration-offline-v1" and state["database"] == "temporary-sqlite"
        assert client.get("/health").json() == {"status": "ok"}
        def post(path, body):
            response = client.post(path, json=body)
            assert response.status_code in (200, 201), (path, response.status_code)
            return response.json()
        a = post("/workspaces", {"name": "Acceptance Workspace A", "tool_settings": {"web_search": True}})["id"]
        b = post("/workspaces", {"name": "Acceptance Workspace B"})["id"]
        def history(session, workspace=a):
            return client.get(f"/sessions/{session}/messages", params={"workspace_id": workspace}).json()
        def run(session, workspace=a):
            return client.get("/agent-runs/latest", params={"workspace_id": workspace, "session_id": session}).json()
        def request(session, prompt, workspace=a, **extra):
            return {"workspace_id": workspace, "session_id": session, "model_id": "deepseek",
                    "messages": [{"role": "user", "content": prompt}], **extra}
        def stream(session, prompt, workspace=a, callback=None, close=False, **extra):
            started, first = time.monotonic(), None
            observed = []
            with client.stream("POST", "/chat/stream", json=request(session, prompt, workspace, **extra)) as response:
                for kind, data in frames(response):
                    observed.append((kind, data))
                    if kind == "message" and first is None:
                        first = (time.monotonic() - started) * 1000
                        if callback:
                            callback(observed)
                        if close:
                            break
            return observed, {"duration_ms": round((time.monotonic() - started) * 1000, 3),
                              "ttft_ms": round(first, 3) if first is not None else None}
        def record(name, events=None, timing=None, **details):
            row = {"id": name, "status": "PASS", **details}
            if events is not None:
                kinds = [kind for kind, _ in events]
                row.update(event_counts=dict(Counter(kinds)), event_prefix=kinds[:8], event_suffix=kinds[-4:])
            if timing:
                row.update(timing)
            rows.append(row)
            print("PASS HTTP " + name, flush=True)
        def complete(session, events):
            kinds = [kind for kind, _ in events]
            assert kinds[-1] == "done" and kinds.count("done") == 1 and "error" not in kinds
            answer = "".join(data["content"] for kind, data in events if kind == "message")
            sources = [data for kind, data in events if kind == "source"]
            saved = history(session)
            assert len(saved) == 2 and saved[-1]["content"] == answer and saved[-1]["sources"] == sources
            assert "[[cite:" not in answer and "<|tool_call" not in answer
            return answer, sources

        before = client.get("/__acceptance/state").json()["provider_calls"]
        result = post("/chat", request("http-simple", "Hello"))
        assert not result["error"] and len(history("http-simple")) == 2
        assert client.get("/__acceptance/state").json()["provider_calls"] == before + 1
        record("simple_sync", model_calls=1)

        events, timing = stream("http-stream", "Hello streaming")
        answer, _ = complete("http-stream", events)
        assert len([1 for kind, _ in events if kind == "message"]) > 1
        record("simple_sse", events, timing)

        assert history("http-simple", b) == []
        before = client.get("/__acceptance/state").json()["provider_calls"]
        events, _ = stream("http-simple", "Hello", b)
        assert events[-1][0] == "error" and client.get("/__acceptance/state").json()["provider_calls"] == before
        record("session_workspace_isolation", events)

        upload = client.post("/files/upload", data={"workspace_id": a, "session_id": "document-seed"},
                             files={"files": ("acceptance-note.txt", b"Synthetic A evidence: release ALPHA.", "text/plain")})
        assert upload.status_code == 200 and upload.json()["ingest_error"] is None
        document = upload.json()["stored"][0]["document_id"]
        assert upload.json()["stored"][0]["status"] == "indexed"
        assert client.get("/files", params={"workspace_id": b}).json()["files"] == []
        events, _ = stream("http-cross-doc", "Research and compare attached knowledge documents", b, document_ids=[document])
        assert events[-1][0] == "error" and history("http-cross-doc", b) == []
        record("document_workspace_isolation", events, indexed_document=document)

        events, timing = stream("http-agent", "Research and compare web with knowledge documents", document_ids=[document])
        answer, sources = complete("http-agent", events)
        kinds = [kind for kind, _ in events]
        assert kinds[0] == "agent_run" and kinds.index("agent_plan") < kinds.index("message")
        assert kinds.index("source") < kinds.index("message")
        assert {source["type"] for source in sources} == {"web", "knowledge"}
        assert [source["citation_id"] for source in sources] == list(range(1, len(sources) + 1))
        assert all(f"【{source['citation_id']}】" in answer for source in sources)
        details = run("http-agent")
        assert details["status"] == "completed" and details["metrics"]["finished"]
        assert details["metrics"]["model_call_count"] == 6 and len(details["steps"]) == 3
        assert client.get(f"/agent-runs/{details['id']}", params={"workspace_id": b}).status_code == 404
        assert client.post(f"/agent-runs/{details['id']}/cancel", params={"workspace_id": b}).status_code == 404
        record("agent_rag_web_citations_metrics", events, timing, run_status=details["status"],
               model_calls=details["metrics"]["model_call_count"], usage=details["metrics"]["usage"],
               source_types=[source["type"] for source in sources])

        memory_path = f"/workspaces/{a}/memories"
        memory = post(memory_path, {"key": "preference", "value": "BLUE", "confirmed": True})
        events, _ = stream("http-memory-blue", "What is my preference?")
        assert "Memory: BLUE" in complete("http-memory-blue", events)[0]
        updated = client.patch(memory_path + "/" + memory["id"], json={"value": "GREEN", "expected_version": 1, "confirmed": True})
        assert updated.status_code == 200 and updated.json()["version"] == 2
        events, _ = stream("http-memory-green", "What is my preference?")
        assert "Memory: GREEN" in complete("http-memory-green", events)[0]
        assert client.get(f"/workspaces/{b}/memories/{memory['id']}").status_code == 404
        assert client.patch(memory_path + "/" + memory["id"], json={"value": "STALE", "expected_version": 1, "confirmed": True}).status_code == 409
        record("memory_update_cross_session", events, new_version=2)

        post("/__acceptance/control", {"memory_enabled": False})
        events, _ = stream("http-memory-off", "What is my preference?")
        assert "Memory:" not in complete("http-memory-off", events)[0]
        assert client.get(memory_path).status_code == 503
        post("/__acceptance/control", {"memory_enabled": True})
        assert client.delete(memory_path + "/" + memory["id"], params={"expected_version": 2}).status_code == 204
        events, _ = stream("http-memory-deleted", "What is my preference?")
        assert "Memory:" not in complete("http-memory-deleted", events)[0]
        record("memory_off_and_deleted", events)

        before = client.get("/__acceptance/state").json()["web_calls"]
        events, _ = stream("http-disabled", "Research and compare web with knowledge documents", b,
                           settings={"web_search": True})
        assert client.get("/__acceptance/state").json()["web_calls"] == before
        assert all(source["type"] != "web" for kind, source in events if kind == "source")
        assert history("http-disabled", b) == [] or run("http-disabled", b)["status"] in {"completed", "partial", "budget_exceeded"}
        record("disabled_tool_not_executed", events, web_executions=0)

        for suffix, prompt in [("failure", "Research and compare fail-model"),
                               ("timeout", "Research and compare timeout"),
                               ("invalid-citation", "Research and compare web knowledge invalid-citation"),
                               ("provider-disconnect", "Research and compare web knowledge disconnect")]:
            session = "http-" + suffix
            events, timing = stream(session, prompt)
            assert any(kind == "error" for kind, _ in events) and not any(kind == "done" for kind, _ in events)
            assert history(session) == [] and run(session)["status"] == "failed"
            assert "【999】" not in "".join(data["content"] for kind, data in events if kind == "message")
            record(suffix, events, timing, failure_type=run(session)["metrics"]["failure_type"])

        post("/__acceptance/control", {"token_budget": 10})
        events, _ = stream("http-budget", "Research and compare web sources")
        assert run("http-budget")["status"] == "budget_exceeded"
        assert run("http-budget")["metrics"]["model_call_count"] == 1
        assert not run("http-budget")["steps"]
        post("/__acceptance/control", {"token_budget": 16000})
        record("token_budget", events, run_status="budget_exceeded")

        def cancel(observed):
            run_id = next(data["run_id"] for kind, data in observed if kind == "agent_run")
            assert client.post(f"/agent-runs/{run_id}/cancel", params={"workspace_id": a}).status_code == 200
        events, timing = stream("http-cancel", "Research and compare web knowledge slow", callback=cancel)
        assert run("http-cancel")["status"] == "cancelled" and history("http-cancel") == []
        assert not any(kind == "done" for kind, _ in events)
        record("explicit_cancel", events, timing, run_status="cancelled")

        events, timing = stream("http-close", "Research and compare web knowledge slow", close=True)
        for _ in range(50):
            if run("http-close")["status"] == "cancelled":
                break
            time.sleep(0.1)
        assert run("http-close")["status"] == "cancelled" and history("http-close") == []
        record("tcp_client_disconnect", events, timing, run_status="cancelled")

        for _ in range(2):
            result = post("/chat", request("http-repeated", "Hello repeated"))
            assert not result["error"]
        assert len(history("http-repeated")) == 4
        record("repeated_post_contract", saved_turns=2, note="Two successful POSTs are two turns, not server-side idempotency")

        for endpoint in ("/chat", "/chat/stream"):
            result = client.post(endpoint, json=request("http-missing", "Research and compare web", "synthetic-missing"))
            assert result.status_code == 200 and "Workspace not found" in result.text
        record("missing_workspace_fixed", saved_messages=0)
        final = client.get("/__acceptance/state").json()
        assert final["blocked_network_attempts"] == 0
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "mode": "real loopback HTTP, actual FastAPI/SQLite/Chroma, Mock Provider/Embedding/Web",
              "scenarios": rows, "summary": {"passed": len(rows), "total": len(rows), "external_api_calls": 0},
              "harness_state": final, "workspace_a": a, "workspace_b": b}
    Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "integration-http-results.json")
