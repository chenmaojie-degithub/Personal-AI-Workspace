from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app
from app.api.routes.chat_stream import _events
from app.models.chat import ChatMessage, ChatRequest, ChatSettings
from app.providers.base import LLMStreamEvent, ProviderToolCall
from app.services.data_analysis import DataAnalysisError, analyze_data
from app.tools.registry import execute_tool_call, get_enabled_tool_specs


class DataAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Path(self.temp.name) / "storage"
        self.workspace = "workspace-a"
        self.other = "workspace-b"
        (self.storage / "workspaces" / self.workspace).mkdir(parents=True)
        (self.storage / "workspaces" / self.other).mkdir(parents=True)
        self.patch = patch.object(settings, "storage_dir", str(self.storage))
        self.patch.start()
        self.frame = pd.DataFrame({
            "name": ["张三", "李四", "王五", "赵六"],
            "class": ["1班", "1班", "2班", "2班"],
            "score": [88, 92, 76, 95],
            "optional": [1, None, 3, None],
        })
        self.csv = self.storage / "workspaces" / self.workspace / "students.csv"
        self.xlsx = self.storage / "workspaces" / self.workspace / "students.xlsx"
        self.frame.to_csv(self.csv, index=False)
        self.frame.to_excel(self.xlsx, index=False)

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp.cleanup()

    def test_switch_controls_tool_and_schema(self) -> None:
        self.assertNotIn("analyze_data", [tool.name for tool in get_enabled_tool_specs(ChatSettings())])
        tool = next(tool for tool in get_enabled_tool_specs(ChatSettings(data_analysis=True), self.workspace) if tool.name == "analyze_data")
        self.assertEqual(tool.parameters_schema["required"], ["file_id", "operation"])
        result = execute_tool_call({tool.name: tool}, tool.name, '{"file_id":"students.csv","operation":"mean","column":"score"}')
        self.assertEqual(result["result"], 87.75)
        with self.assertRaisesRegex(ValueError, "Unexpected tool arguments"):
            execute_tool_call({tool.name: tool}, tool.name, '{"file_id":"students.csv","operation":"mean","column":"score","code":"print(1)"}')
        with self.assertRaisesRegex(ValueError, "invalid type"):
            execute_tool_call({tool.name: tool}, tool.name, '{"file_id":"students.csv","operation":"top_n","column":"score","limit":"10"}')

    def test_csv_and_xlsx_load(self) -> None:
        for name in ("students.csv", "students.xlsx"):
            result = analyze_data(self.workspace, name, "shape")
            self.assertEqual((result["rows"], result["columns"]), (4, 4))

    def test_operations(self) -> None:
        self.assertEqual(analyze_data(self.workspace, "students.csv", "mean", column="score")["result"], 87.75)
        top = analyze_data(self.workspace, "students.csv", "top_n", column="score", limit=2)
        self.assertEqual([row["name"] for row in top["rows"]], ["赵六", "李四"])
        grouped = analyze_data(self.workspace, "students.csv", "group_by", column="score", group_by="class")
        self.assertEqual([row["mean"] for row in grouped["rows"]], [90.0, 85.5])
        missing = analyze_data(self.workspace, "students.csv", "missing_values")
        self.assertEqual(missing["result"]["optional"], 2)

    def test_rejects_invalid_operation_column_type_and_paths(self) -> None:
        with self.assertRaisesRegex(DataAnalysisError, "Unsupported operation"):
            analyze_data(self.workspace, "students.csv", "python")
        with self.assertRaisesRegex(DataAnalysisError, "does not exist"):
            analyze_data(self.workspace, "students.csv", "mean", column="missing")
        with self.assertRaisesRegex(DataAnalysisError, "must be numeric"):
            analyze_data(self.workspace, "students.csv", "mean", column="name")
        for file_id in ("../students.csv", str(self.csv), "..\\students.csv"):
            with self.assertRaisesRegex(DataAnalysisError, "Invalid file_id"):
                analyze_data(self.workspace, file_id, "shape")

    def test_workspace_isolation(self) -> None:
        with self.assertRaisesRegex(DataAnalysisError, "not accessible"):
            analyze_data(self.other, "students.csv", "shape")

    def test_chart_is_generated_and_served(self) -> None:
        results = [
            analyze_data(self.workspace, "students.csv", "chart", column="score", chart_type=kind)
            for kind in ("bar", "line", "pie")
        ]
        results.append(analyze_data(
            self.workspace, "students.csv", "chart", chart_type="scatter",
            x_column="score", y_column="optional",
        ))
        results.append(analyze_data(
            self.workspace, "students.csv", "chart", chart_type="bar",
            x_column="score", y_column="optional",
        ))
        for result in results:
            self.assertEqual(result["type"], "chart")
            self.assertTrue((self.storage / "analysis_charts" / self.workspace / Path(result["url"]).name).is_file())
        response = TestClient(create_app()).get(results[0]["url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")

    def test_chart_storage_is_bounded(self) -> None:
        directory = self.storage / "analysis_charts" / self.workspace
        directory.mkdir(parents=True)
        for index in range(50):
            (directory / f"old-{index}.png").write_bytes(b"old")
        analyze_data(self.workspace, "students.csv", "chart", column="score", chart_type="bar")
        self.assertEqual(len(list(directory.glob("*.png"))), 50)

    def test_stream_executes_tool_and_emits_only_final_answer_and_chart(self) -> None:
        class Provider:
            calls = 0

            def stream(self, messages, tools=None):
                self.calls += 1
                if self.calls == 1:
                    yield LLMStreamEvent("message", content="<hidden preamble>")
                    yield LLMStreamEvent("tool_call", tool_call=ProviderToolCall(
                        "call-1", "analyze_data", '{"file_id":"students.csv","operation":"columns"}',
                    ))
                elif self.calls == 2:
                    yield LLMStreamEvent("tool_call", tool_call=ProviderToolCall(
                        "call-2", "analyze_data",
                        '{"file_id":"students.csv","operation":"chart","column":"score","chart_type":"bar"}',
                    ))
                else:
                    yield LLMStreamEvent("message", content="成绩图表已生成。")
                yield LLMStreamEvent("done", provider="test", model="test")

        req = ChatRequest(
            workspace_id=self.workspace,
            messages=[ChatMessage(role="user", content="生成成绩图")],
            settings=ChatSettings(data_analysis=True),
        )
        with patch("app.api.routes.chat_stream.resolve_workspace_request", side_effect=lambda value: value), patch(
            "app.api.routes.chat_stream.create_llm_provider", return_value=Provider()
        ), patch("app.api.routes.chat_stream.resolve_model") as model, patch(
            "app.api.routes.chat_stream._should_use_rag", return_value=False
        ), patch("app.api.routes.chat_stream.save_chat_turn"):
            model.return_value.supports_tools = True
            events = [
                (item.split("\n", 1)[0].removeprefix("event: "), json.loads(item.split("data: ", 1)[1]))
                for item in _events(req)
            ]
        content = "".join(data["content"] for kind, data in events if kind == "message")
        self.assertEqual(content, "成绩图表已生成。")
        self.assertNotIn("hidden", content)
        self.assertEqual([data["name"] for kind, data in events if kind == "tool_call"], ["analyze_data", "analyze_data"])
        charts = [data for kind, data in events if kind == "chart"]
        self.assertEqual(len(charts), 1)
        self.assertTrue(charts[0]["url"].endswith(".png"))


if __name__ == "__main__":
    unittest.main()
