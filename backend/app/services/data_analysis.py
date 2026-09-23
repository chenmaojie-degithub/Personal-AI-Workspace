from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import uuid4

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from app.core.config import settings

Operation = Literal["describe", "columns", "shape", "missing_values", "mean", "median", "min", "max", "sum", "count", "value_counts", "group_by", "top_n", "sort", "chart"]
ChartType = Literal["bar", "line", "pie", "scatter"]
OPERATIONS = {"describe", "columns", "shape", "missing_values", "mean", "median", "min", "max", "sum", "count", "value_counts", "group_by", "top_n", "sort", "chart"}
CHART_TYPES = {"bar", "line", "pie", "scatter"}
MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 200
MAX_CHARTS_PER_WORKSPACE = 50


class DataAnalysisError(Exception):
    pass


def list_analysis_files(workspace_id: str) -> list[str]:
    directory = _workspace_dir(workspace_id)
    return sorted(path.name for path in directory.iterdir() if path.is_file() and path.suffix.lower() in {".csv", ".xlsx"}) if directory.is_dir() else []


def analyze_data(
    workspace_id: str,
    file_id: str,
    operation: str,
    column: str | None = None,
    group_by: str | None = None,
    limit: int | None = None,
    chart_type: str | None = None,
    x_column: str | None = None,
    y_column: str | None = None,
) -> dict:
    if operation not in OPERATIONS:
        raise DataAnalysisError(f"Unsupported operation: {operation}.")
    path = _resolve_file(workspace_id, file_id)
    frame = _load(path)
    columns = [str(value) for value in frame.columns]
    frame.columns = columns
    size = min(max(limit or 10, 1), 100)

    if operation == "columns":
        return {"operation": operation, "file_id": file_id, "columns": columns}
    if operation == "shape":
        return {"operation": operation, "file_id": file_id, "rows": len(frame), "columns": len(columns)}
    if operation == "missing_values":
        return {"operation": operation, "file_id": file_id, "result": {name: int(value) for name, value in frame.isna().sum().items()}}
    if operation == "describe":
        numeric = [str(value) for value in frame.select_dtypes(include="number").columns]
        return {
            "operation": operation, "file_id": file_id, "rows": len(frame), "columns": columns,
            "numeric_columns": numeric,
            "missing_values": {name: int(value) for name, value in frame.isna().sum().items() if value},
            "summary": _records(frame[numeric].describe().round(6).reset_index()) if numeric else [],
        }
    if operation == "count" and column is None:
        return {"operation": operation, "file_id": file_id, "result": len(frame)}
    if operation in {"mean", "median", "min", "max", "sum", "count"}:
        series = _column(frame, column)
        if operation != "count" and not pd.api.types.is_numeric_dtype(series):
            raise DataAnalysisError(f'Column "{column}" must be numeric for {operation}.')
        result = getattr(series, operation)()
        return {"operation": operation, "file_id": file_id, "column": column, "result": _value(result)}
    if operation == "value_counts":
        series = _column(frame, column)
        result = series.value_counts(dropna=False).head(size).rename_axis(str(column)).reset_index(name="count")
        return {"operation": operation, "file_id": file_id, "column": column, "rows": _records(result)}
    if operation in {"top_n", "sort"}:
        _column(frame, column)
        result = frame.sort_values(str(column), ascending=False).head(size)
        return {"operation": operation, "file_id": file_id, "column": column, "columns": columns, "rows": _records(result)}
    if operation == "group_by":
        _column(frame, group_by)
        values = _column(frame, column)
        if not pd.api.types.is_numeric_dtype(values):
            raise DataAnalysisError(f'Column "{column}" must be numeric for group_by.')
        result = frame.groupby(str(group_by), dropna=False)[str(column)].agg(["count", "mean", "min", "max"]).round(6).reset_index()
        return {"operation": operation, "file_id": file_id, "group_by": group_by, "column": column, "rows": _records(result.head(100))}
    return _chart(frame, workspace_id, file_id, column, group_by, chart_type, x_column, y_column)


def _workspace_dir(workspace_id: str) -> Path:
    if not workspace_id or workspace_id in {".", ".."} or "/" in workspace_id or "\\" in workspace_id:
        raise DataAnalysisError("Invalid workspace_id.")
    root = (Path(settings.storage_dir).resolve() / "workspaces").resolve()
    target = (root / workspace_id).resolve()
    if target.parent != root:
        raise DataAnalysisError("Invalid workspace_id.")
    return target


def _resolve_file(workspace_id: str, file_id: str) -> Path:
    if not file_id or Path(file_id).name != file_id or file_id.startswith("."):
        raise DataAnalysisError("Invalid file_id.")
    path = (_workspace_dir(workspace_id) / file_id).resolve()
    if path.parent != _workspace_dir(workspace_id):
        raise DataAnalysisError("Invalid file_id.")
    if not path.is_file():
        raise DataAnalysisError("File not found or is not accessible in this Workspace.")
    if path.suffix.lower() not in {".csv", ".xlsx"}:
        raise DataAnalysisError("Unsupported file type. Only CSV and XLSX are supported.")
    if path.stat().st_size > MAX_BYTES:
        raise DataAnalysisError("File is too large. Maximum size is 10 MB.")
    return path


def _load(path: Path) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, nrows=MAX_ROWS + 1) if path.suffix.lower() == ".csv" else pd.read_excel(path, nrows=MAX_ROWS + 1, engine="openpyxl")
    except Exception as exc:
        raise DataAnalysisError(f"Could not read {path.suffix.upper()[1:]} file: {exc}") from exc
    if len(frame) > MAX_ROWS:
        raise DataAnalysisError(f"File exceeds the {MAX_ROWS} row limit.")
    if len(frame.columns) > MAX_COLUMNS:
        raise DataAnalysisError(f"File exceeds the {MAX_COLUMNS} column limit.")
    return frame


def _column(frame: pd.DataFrame, name: str | None) -> pd.Series:
    if not name or name not in frame.columns:
        raise DataAnalysisError(f'Column "{name}" does not exist. Available columns: {list(frame.columns)}')
    return frame[name]


def _value(value):
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _records(frame: pd.DataFrame) -> list[dict]:
    return [{str(key): _value(value) for key, value in row.items()} for row in frame.to_dict(orient="records")]


def _chart(frame: pd.DataFrame, workspace_id: str, file_id: str, column: str | None, group_by: str | None, chart_type: str | None, x_column: str | None, y_column: str | None) -> dict:
    if chart_type not in CHART_TYPES:
        raise DataAnalysisError(f"Unsupported chart_type: {chart_type}.")
    fig, ax = plt.subplots(figsize=(8, 4.5))
    try:
        if chart_type == "scatter":
            x, y = _column(frame, x_column), _column(frame, y_column)
            if not pd.api.types.is_numeric_dtype(x) or not pd.api.types.is_numeric_dtype(y):
                raise DataAnalysisError("Scatter chart columns must be numeric.")
            ax.scatter(x, y)
            ax.set(xlabel=x_column, ylabel=y_column, title=f"{y_column} by {x_column}")
        elif x_column and y_column:
            x, y = _column(frame, x_column), _column(frame, y_column)
            if not pd.api.types.is_numeric_dtype(y):
                raise DataAnalysisError(f'Column "{y_column}" must be numeric for {chart_type} charts.')
            values = frame[[x_column, y_column]].head(100)
            if chart_type == "pie":
                ax.pie(values[y_column], labels=values[x_column].astype(str))
            elif chart_type == "bar":
                ax.bar(values[x_column].astype(str), values[y_column])
            else:
                ax.plot(values[x_column], values[y_column])
            ax.set(xlabel=x_column, ylabel=y_column, title=f"{y_column} by {x_column}")
        else:
            values = _column(frame, column)
            if group_by:
                _column(frame, group_by)
                if not pd.api.types.is_numeric_dtype(values):
                    raise DataAnalysisError(f'Column "{column}" must be numeric for grouped charts.')
                plot = frame.groupby(group_by, dropna=False)[str(column)].mean().head(30)
            else:
                plot = values.value_counts(dropna=False).head(20)
            getattr(plot.plot, chart_type)(ax=ax)
            ax.set_title(f"{column} {chart_type} chart")
        fig.tight_layout()
        directory = Path(settings.storage_dir).resolve() / "analysis_charts" / workspace_id
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid4().hex}.png"
        fig.savefig(directory / filename, dpi=140)
        for old_chart in sorted(directory.glob("*.png"), key=lambda path: path.stat().st_mtime, reverse=True)[MAX_CHARTS_PER_WORKSPACE:]:
            try:
                old_chart.unlink(missing_ok=True)
            except OSError:
                pass
    finally:
        plt.close(fig)
    return {"type": "chart", "operation": "chart", "file_id": file_id, "chart_type": chart_type, "url": f"/analysis-charts/{workspace_id}/{filename}", "title": ax.get_title()}
