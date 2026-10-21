"""Offline regression of citation identities, streaming, HTTP, and saved history."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack, closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agents.orchestrator import run_agent
from app.api.routes.chat_stream import _events
from app.core import database
from app.main import app
from app.models.chat import ChatRequest, CitationSource
from app.providers.base import LLMResponse, LLMStreamEvent, ProviderToolCall
from app.services.citations import CitationError, CitationRegistry, CitationStream


def catalog(messages):
    content = next(item["content"] for item in reversed(messages)
                   if item["content"].startswith("CITATION_CATALOG"))
    return json.loads(content.split(": ", 1)[1].split("\n", 1)[0])


# URLs from the existing acceptance report; no new Exa or LLM requests.
WEB_RESULTS = [
    {"title": "Youtu-Agent", "url": "https://github.com/Tencent/Youtu-agent/", "snippet": "Agent framework"},
    {"title": "JoyAgent", "url": "https://github.com/jd-opensource/JoyAgent-JDGenie", "snippet": "Agent framework"},
    {"title": "Qwen-Agent", "url": "https://github.com/QwenLM/Qwen-Agent/blob/31a4d36d/README_CN.md", "snippet": "Agent framework"},
]
KNOWLEDGE_RESULT = {"type": "knowledge_search", "results": [
    {"document_id": "doc-1", "filename": "note.txt", "chunk_index": 0, "content": "Local document evidence"},
]}


class ReplayProvider:
    """A deterministic model double that copies markers from the real request catalog."""
    def __init__(self, agent=False, invalid=None, fail=False):
        self.agent = agent
        self.invalid = invalid
        self.fail = fail
        self.calls = 0
        self.closed = False

    def complete(self, messages, tools=None, max_tokens=None):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse('{"steps":["Search web","Check document","Answer"]}', (), "replay", "offline")
        names = {2: "search_web", 3: "search_web", 4: "search_knowledge"}
        name = names.get(self.calls)
        calls = (ProviderToolCall(str(self.calls), name, json.dumps({"query": f"query-{self.calls}"})),) if name else ()
        return LLMResponse("" if calls else "FINAL_READY", calls, "replay", "offline")

    def stream(self, messages, tools=None, max_tokens=None):
        try:
            if not self.agent and not catalog(messages):
                yield LLMStreamEvent("tool_call", tool_call=ProviderToolCall("web", "search_web", '{"query":"agent frameworks"}'))
            else:
                entries = catalog(messages)
                qwen = next(item for item in entries if item.get("title") == "Qwen-Agent")
                answer = "\nQwen-Agent " + (self.invalid or qwen["marker"])
                knowledge = next((item for item in entries if item["type"] == "knowledge"), None)
                if knowledge:
                    answer += "；本地资料 " + knowledge["marker"]
                answer += "\n"
                # Every character is a separate provider delta, including marker delimiters.
                for char in answer:
                    yield LLMStreamEvent("message", content=char)
                if self.fail:
                    raise RuntimeError("offline simulated disconnect")
            yield LLMStreamEvent("done", model="replay", provider="offline")
        finally:
            self.closed = True


class CitationTests(unittest.TestCase):
    def registry(self):
        registry = CitationRegistry()
        registry.add(CitationSource(type="web", **{key: item[key] for key in ("title", "url")}) for item in WEB_RESULTS)
        return registry

    def test_stable_ids_across_tool_calls_duplicates_and_mixed_sources(self):
        registry = self.registry()
        marker = catalog([registry.prompt()])[2]["marker"]
        registry.add([CitationSource(type="web", url=WEB_RESULTS[0]["url"], title="duplicate")])
        registry.add([CitationSource(document_id="doc-1", filename="note.txt", chunk_index=0)])
        registry.add([CitationSource(document_id="doc-1", filename="note.txt", chunk_index=0)])
        self.assertEqual([item.citation_id for item in registry.sources], [1, 2, 3, 4])
        self.assertEqual(registry.render("Qwen " + marker), "Qwen 【3】")
        self.assertEqual(registry.sources[2].url, WEB_RESULTS[2]["url"])
        single = CitationRegistry()
        single.add([registry.sources[2]])
        self.assertEqual(single.render(marker), "【1】")

    def test_every_split_has_same_visible_text(self):
        registry = self.registry()
        text = "Qwen " + catalog([registry.prompt()])[2]["marker"] + "。"
        for boundary in range(len(text) + 1):
            with self.subTest(boundary=boundary):
                stream = CitationStream(registry)
                self.assertEqual(stream.feed(text[:boundary]) + stream.feed(text[boundary:]) + stream.finish(), "Qwen 【3】。")

    def test_invalid_numeric_unknown_and_incomplete_markers_fail_closed(self):
        registry = self.registry()
        for text in ("【2】", "[3]", "[999]", "[[cite:0000000000000000]]", "[[cite:bad]]", "[[cite:", "【3"):
            with self.subTest(text=text), self.assertRaises(CitationError):
                registry.render(text)
        stream = CitationStream(registry)
        self.assertEqual(stream.feed("prefix [[cite:"), "prefix ")
        with self.assertRaises(CitationError):
            stream.feed("0000000000000000]]")

    def test_prose_markdown_and_code_survive_character_chunks(self):
        registry = self.registry()
        text = "[Guide](https://example.com) [[wiki]] `a[1]` ``a`[2]``\n```py\na = '[3]' # `\n```\n\\[4] and prose [ `a[5]` ]\n~~~py\na[6]\n~~~~\n"
        stream = CitationStream(registry)
        self.assertEqual("".join(stream.feed(char) for char in text) + stream.finish(), text)
        with self.assertRaises(CitationError):
            registry.render("```py\nx = '[1]'\n```\n[9]")

    def test_numeric_data_does_not_require_sources_or_code_formatting(self):
        for registry in (CitationRegistry(), self.registry()):
            text = "列表为 [1, 2]，范围 [1-3]。"
            stream = CitationStream(registry)
            self.assertEqual("".join(stream.feed(char) for char in text) + stream.finish(), text)
        empty = CitationRegistry()
        self.assertEqual(empty.render("数组 [1]，空数组 []，未闭合列表 [1, 2"), "数组 [1]，空数组 []，未闭合列表 [1, 2")
        for text in ("【1】", "[[cite:0000000000000000]]", "[[cite:", "[[ci"):
            with self.subTest(text=text), self.assertRaises(CitationError):
                empty.render(text)


class CitationHttpTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(database.settings, "database_url", "sqlite:///" + (Path(self.directory.name) / "test.db").as_posix()))
        self.stack.enter_context(patch("app.services.search_providers.ExaProvider.search", side_effect=AssertionError("Live Exa forbidden")))
        self.client = TestClient(app)

    def tearDown(self):
        self.stack.close()
        self.directory.cleanup()

    def install(self, provider):
        self.stack.enter_context(patch("app.api.routes.chat_stream.create_llm_provider", return_value=provider))
        self.stack.enter_context(patch("app.agents.orchestrator.create_llm_provider", return_value=provider))
        self.stack.enter_context(patch("app.tools.registry.web_search", return_value={"results": WEB_RESULTS}))
        self.stack.enter_context(patch("app.tools.registry.search_knowledge", return_value=KNOWLEDGE_RESULT))

    def request(self, agent=False):
        return {"session_id": "citation-test", "settings": {"web_search": True}, "messages": [{
            "role": "user", "content": "Research and compare web sources with the knowledge document" if agent else "search the web for agent frameworks",
        }]}

    def post(self, agent=False):
        response = self.client.post("/chat/stream", json=self.request(agent))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(response.headers["cache-control"], "no-cache")
        return [(block.splitlines()[0][7:], json.loads(block.split("data: ", 1)[1])) for block in response.text.strip().split("\n\n")]

    def test_http_direct_and_agent_match_sources_and_persisted_history(self):
        for agent in (False, True):
            with self.subTest(agent=agent):
                provider = ReplayProvider(agent=agent)
                self.install(provider)
                events = self.post(agent)
                kinds = [kind for kind, _ in events]
                self.assertNotIn("error", kinds)
                self.assertEqual(kinds[-1], "done")
                self.assertLess(kinds.index("source"), kinds.index("message"))
                sources = [data for kind, data in events if kind == "source"]
                content = "".join(data["content"] for kind, data in events if kind == "message")
                self.assertIn("Qwen-Agent 【3】", content)
                self.assertEqual(sources[2]["url"], WEB_RESULTS[2]["url"])
                self.assertEqual([item["citation_id"] for item in sources], list(range(1, len(sources) + 1)))
                if agent:
                    self.assertEqual(len(sources), 4)
                    self.assertIn("本地资料 【4】", content)
                    self.assertTrue(any(kind == "agent_status" and data["status"] == "completed" for kind, data in events))
                history = self.client.get("/sessions/citation-test/messages").json()
                self.assertEqual(history[-1]["content"], content)
                self.assertEqual(history[-1]["sources"], sources)
                self.assertTrue(provider.closed)

    def test_http_invalid_citation_or_failure_never_saves_partial_answer(self):
        for agent in (False, True):
            for invalid, fail in (("【2】", False), ("[999]", False), ("[[cite:0000000000000000]]", False), ("[[cite:", False), (None, True)):
                with self.subTest(agent=agent, invalid=invalid, fail=fail):
                    self.install(ReplayProvider(agent=agent, invalid=invalid, fail=fail))
                    events = self.post(agent)
                    self.assertIn("error", [kind for kind, _ in events])
                    self.assertNotIn("done", [kind for kind, _ in events])
                    text = "".join(data["content"] for kind, data in events if kind == "message")
                    if invalid:
                        self.assertNotIn(invalid, text)
                    self.assertEqual(self.client.get("/sessions/citation-test/messages").json(), [])

    def test_generator_close_mid_marker_closes_provider_and_does_not_save(self):
        for agent in (False, True):
            with self.subTest(agent=agent):
                provider = ReplayProvider(agent=agent)
                def mid_marker(*args, **kwargs):
                    try:
                        yield LLMStreamEvent("message", content="prefix [[cite:")
                        yield LLMStreamEvent("message", content="0000000000000000]]")
                    finally:
                        provider.closed = True
                provider.stream = mid_marker
                self.install(provider)
                req = ChatRequest.model_validate(self.request(agent))
                if not agent:
                    req = ChatRequest(messages=[{"role": "user", "content": "hello"}])
                iterator = run_agent(req) if agent else _events(req)
                for item in iterator:
                    if (item[0] if agent else item.splitlines()[0][7:]) == "message":
                        break
                iterator.close()
                self.assertTrue(provider.closed)
                self.assertEqual(self.client.get("/sessions/citation-test/messages").json(), [])

    def test_nonstream_chat_uses_same_catalog_and_rejects_unbound_number(self):
        for invalid in (False, True):
            with self.subTest(invalid=invalid):
                def complete(messages, tools=None):
                    entries = catalog(messages)
                    if not entries:
                        return LLMResponse("", (ProviderToolCall("web", "search_web", '{"query":"frameworks"}'),))
                    return LLMResponse("[3]" if invalid else "Qwen-Agent " + entries[2]["marker"])
                self.install(ReplayProvider())
                with patch("app.api.routes.chat.create_llm_provider", return_value=SimpleNamespace(complete=complete)):
                    body = self.request()
                    body["session_id"] = "invalid" if invalid else "valid"
                    result = self.client.post("/chat", json=body).json()
                if invalid:
                    self.assertIsNotNone(result["error"])
                    self.assertEqual(self.client.get("/sessions/invalid/messages").json(), [])
                else:
                    self.assertIsNone(result["error"])
                    self.assertEqual(result["assistant_message"]["content"], "Qwen-Agent 【3】")
                    self.assertEqual(result["sources"][2]["url"], WEB_RESULTS[2]["url"])

    def test_plain_chat_numeric_data_survives_http_and_history(self):
        text = "数组 [1]，列表 [1, 2]。"
        def stream(*args, **kwargs):
            for char in text:
                yield LLMStreamEvent("message", content=char)
            yield LLMStreamEvent("done", model="offline", provider="offline")
        body = {"session_id": "plain-numbers", "messages": [{"role": "user", "content": "Explain an array"}]}
        with patch("app.api.routes.chat_stream.create_llm_provider", return_value=SimpleNamespace(stream=stream)):
            response = self.client.post("/chat/stream", json=body)
        events = [json.loads(block.split("data: ", 1)[1]) for block in response.text.strip().split("\n\n")
                  if block.startswith("event: message\n")]
        self.assertEqual("".join(item["content"] for item in events), text)
        history = self.client.get("/sessions/plain-numbers/messages").json()
        self.assertEqual(history[-1]["content"], text)
        self.assertEqual(history[-1]["sources"], [])
        with patch("app.api.routes.chat.create_llm_provider", return_value=SimpleNamespace(
            complete=lambda **kwargs: LLMResponse(text),
        )):
            response = self.client.post("/chat", json={**body, "session_id": "plain-numbers-sync"}).json()
        self.assertIsNone(response["error"])
        self.assertEqual(response["assistant_message"]["content"], text)

    def test_nonstream_agent_receives_catalog_for_final_answer(self):
        provider = ReplayProvider(agent=True)
        def complete(messages, tools=None, max_tokens=None):
            response = provider.complete(messages, tools, max_tokens)
            if response.content == "FINAL_READY":
                response = LLMResponse("Qwen-Agent " + catalog(messages)[2]["marker"])
            return response
        self.install(provider)
        with patch("app.agents.orchestrator.create_llm_provider", return_value=SimpleNamespace(complete=complete)):
            result = self.client.post("/chat", json=self.request(agent=True)).json()
        self.assertIsNone(result["error"])
        self.assertEqual(result["assistant_message"]["content"], "Qwen-Agent 【3】")

    def test_legacy_sqlite_messages_gain_empty_sources_without_rewriting_text(self):
        legacy_path = Path(self.directory.name) / "legacy.db"
        with closing(sqlite3.connect(legacy_path)) as connection:
            connection.execute("CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, created_at TEXT)")
            connection.execute("INSERT INTO chat_messages VALUES (1, 'legacy', 'assistant', 'Old [2]', '2026-10-13')")
            connection.commit()
        with patch.object(database.settings, "database_url", "sqlite:///" + legacy_path.as_posix()):
            history = database.list_messages("legacy")
        self.assertEqual(history[0]["content"], "Old [2]")
        self.assertEqual(history[0]["sources"], [])
