from __future__ import annotations

from app.services.data_analysis import DataAnalysisError, analyze_data as run_analysis


def analyze_data(workspace_id: str | None, **arguments) -> dict:
    if not workspace_id:
        return {"error": "Data Analysis requires a Workspace."}
    try:
        return run_analysis(workspace_id=workspace_id, **arguments)
    except DataAnalysisError as exc:
        return {"error": str(exc), "operation": arguments.get("operation"), "file_id": arguments.get("file_id")}
