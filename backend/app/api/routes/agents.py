from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.agents.orchestrator import cancel_agent_run
from app.core.database import get_agent_run, latest_agent_run

router = APIRouter(prefix="/agent-runs", tags=["agents"])


@router.get("/latest")
def latest(session_id: str = Query(min_length=1), workspace_id: str = Query(min_length=1)) -> dict | None:
    return latest_agent_run(session_id, workspace_id)


@router.get("/{run_id}")
def get_run(run_id: str, workspace_id: str = Query(min_length=1)) -> dict:
    run = get_agent_run(run_id, workspace_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


@router.post("/{run_id}/cancel")
def cancel(run_id: str, workspace_id: str = Query(min_length=1)) -> dict:
    run = cancel_agent_run(run_id, workspace_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run
