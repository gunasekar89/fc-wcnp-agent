"""FastAPI server exposing K-Agent capabilities."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException

from ..agent_core import AgentCore
from .webhook_handler import router as webhook_router

app = FastAPI(title="K-Agent API", version="0.1.0")
app.include_router(webhook_router)
agent = AgentCore()


@app.get("/healthz")
def health() -> dict:
    return {"status": "ok"}


@app.post("/diagnose")
def diagnose(payload: dict) -> dict:
    query = payload.get("query")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    namespace: Optional[str] = payload.get("namespace")
    return agent.process_user_query(query, namespace=namespace)


@app.post("/execute")
def execute(plan: dict) -> dict:
    try:
        outcomes = agent.approve_and_execute(plan)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"outcomes": outcomes}


@app.get("/activity")
def activity() -> dict:
    return {"audit": agent.recent_activity()}
