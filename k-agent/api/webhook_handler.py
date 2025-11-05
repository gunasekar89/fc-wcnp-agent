"""Webhook endpoints for integrating external systems with K-Agent."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..agent_core import AgentCore

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
agent = AgentCore()


@router.post("/alert")
def ingest_alert(payload: dict) -> dict:
    alert_name = payload.get("alert")
    description = payload.get("description", "")
    if not alert_name:
        raise HTTPException(status_code=400, detail="alert field required")
    query = f"Alert {alert_name} triggered. {description}"
    return agent.process_user_query(query)


@router.post("/approval")
def approval(payload: dict) -> dict:
    plan = payload.get("plan")
    if not plan:
        raise HTTPException(status_code=400, detail="plan missing")
    try:
        outcomes = agent.approve_and_execute(plan)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"status": "executed", "outcomes": outcomes}
