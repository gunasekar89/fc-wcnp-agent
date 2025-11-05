"""Pydantic models used across K-Agent.

These models provide typed structures for Kubernetes contexts, diagnostic
insights, remediation plans, and audit records. They are intentionally rich to
support advanced reasoning and automation layers built on top of them.
"""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class SeverityLevel(str, Enum):
    """Represents the severity of a diagnostic finding."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ClusterContext(BaseModel):
    """Information about the cluster and namespace the agent is targeting."""

    name: str = Field(..., description="Kubernetes cluster name derived from kubeconfig")
    namespace: str = Field(..., description="Active namespace for the current session")
    user: Optional[str] = Field(None, description="Authenticated user or service account")
    available_namespaces: List[str] = Field(default_factory=list)
    rbac_roles: List[str] = Field(default_factory=list, description="RBAC roles detected for the user")
    topology: Dict[str, List[str]] = Field(default_factory=dict, description="Mapping of nodes -> workloads")


class DiagnosticIssue(BaseModel):
    """Represents a concrete problem discovered during validation."""

    identifier: str = Field(..., description="Deterministic key for deduplication")
    title: str
    description: str
    severity: SeverityLevel
    category: str = Field(..., description="Domain such as compute, network, storage, etc.")
    evidence: Dict[str, str] = Field(default_factory=dict)
    recommendation: Optional[str] = None


class DiagnosticReport(BaseModel):
    """Aggregated output from the validator."""

    context: ClusterContext
    issues: List[DiagnosticIssue] = Field(default_factory=list)
    generated_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)

    @property
    def has_blockers(self) -> bool:
        return any(issue.severity in {SeverityLevel.ERROR, SeverityLevel.CRITICAL} for issue in self.issues)

    @property
    def summary(self) -> str:
        count = len(self.issues)
        highest = max((issue.severity for issue in self.issues), default=SeverityLevel.INFO)
        return f"{count} issues detected. Highest severity: {highest}."


class RemediationAction(BaseModel):
    """A single remediation step that can be executed by the executor."""

    action_id: str
    title: str
    description: str
    command: Optional[str] = Field(None, description="kubectl or helm command to apply")
    dry_run_command: Optional[str] = Field(None, description="Command used for dry-run evaluation")
    requires_approval: bool = True
    metadata: Dict[str, str] = Field(default_factory=dict)


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ExecutionPlan(BaseModel):
    """Represents a sequence of remediation actions."""

    plan_id: str
    context: ClusterContext
    actions: List[RemediationAction]
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    rollback_plan: Optional[str] = Field(None, description="Description of rollback strategy")


class AuditRecord(BaseModel):
    """Log entry capturing significant events and state transitions."""

    event_id: str
    timestamp: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    actor: str
    action: str
    status: str
    metadata: Dict[str, str] = Field(default_factory=dict)


class KnowledgeArticle(BaseModel):
    """Represents an automatically generated runbook entry."""

    article_id: str
    title: str
    summary: str
    body: str
    tags: List[str] = Field(default_factory=list)
    related_issue_ids: List[str] = Field(default_factory=list)


class MonitoringSignal(BaseModel):
    """Data captured from Prometheus, logs, or tracing systems."""

    source: str
    metric: str
    value: float
    window: str
    labels: Dict[str, str] = Field(default_factory=dict)
    captured_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class ActionOutcome(BaseModel):
    """Represents the result of executing a remediation action."""

    action_id: str
    success: bool
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    started_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    finished_at: Optional[dt.datetime] = None
    retries: int = 0
