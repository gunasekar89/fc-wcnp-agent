"""Core reasoning engine for K-Agent."""

from __future__ import annotations

import logging
import os
import random
import subprocess
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import yaml

from .executor import RemediationExecutor
from .kubectl_runner import KubectlRunner
from .models import (
    AuditRecord,
    ClusterContext,
    DiagnosticIssue,

    ExecutionPlan,
    KnowledgeArticle,
)
from .security import SecurityManager
from .storage.history_manager import HistoryManager
from .storage.sqlite_db import SQLiteStorage
from .validator import Validator

logger = logging.getLogger(__name__)


class SyntheticLLM:
    """A placeholder LLM that crafts responses based on heuristics."""

    def __init__(self, personas: Optional[List[str]] = None) -> None:
        self.personas = personas or ["pragmatic", "observant", "cautious"]

    def summarise(self, query: str, issues: List[DiagnosticIssue]) -> str:
        if not issues:
            return (
                "No critical issues detected. Continue monitoring and ensure alerts are configured "
                "for early anomaly detection."
            )
        highlights = ", ".join(issue.title for issue in issues[:3])
        persona = random.choice(self.personas)
        return f"[{persona}] Investigated '{query}'. Key findings: {highlights}."

    def recommend(self, issues: List[DiagnosticIssue]) -> List[str]:
        recommendations = []
        for issue in issues:
            if issue.recommendation:
                recommendations.append(issue.recommendation)
        if not recommendations:
            recommendations.append("No immediate action required; validate observability baselines.")
        return recommendations

    def draft_runbook(self, issues: List[DiagnosticIssue]) -> KnowledgeArticle:
        body_lines = [f"- {issue.title}: {issue.description}" for issue in issues]
        return KnowledgeArticle(
            article_id=f"auto-{random.randint(1000, 9999)}",
            title="Automated Diagnostic Summary",
            summary=f"Captured {len(issues)} notable findings.",
            body="\n".join(body_lines),
            tags=[issue.category for issue in issues],
            related_issue_ids=[issue.identifier for issue in issues],
        )


class AgentCore:
    """Coordinates diagnostics, reasoning, and remediation planning."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or Path(__file__).resolve().parent / "config" / "config.yaml"
        self.config = self._load_config(self.config_path)
        self.memory: Deque[Dict[str, str]] = deque(maxlen=self.config.get("conversation_memory", 8))

        config_dir = self.config_path.parent
        package_root = config_dir.parent
        kubeconfig = os.getenv("KUBECONFIG")
        self.runner = KubectlRunner(Path(kubeconfig) if kubeconfig else None, dry_run=self.config.get("dry_run", True))
        self.validator = Validator(self.runner)

        rules_file = Path(self.config["safety"]["rules_file"])
        if not rules_file.is_absolute():
            rules_file = (config_dir / rules_file).resolve()
        self.security = SecurityManager(rules_file)

        storage_cfg = self.config["storage"]
        db_path = Path(storage_cfg["db_path"])
        if not db_path.is_absolute():
            db_path = (package_root / db_path).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage = SQLiteStorage(db_path)

        history_file = Path(storage_cfg["history_file"])
        if not history_file.is_absolute():
            history_file = (package_root / history_file).resolve()
        history_file.parent.mkdir(parents=True, exist_ok=True)
        self.history = HistoryManager(self.storage, history_file)

        self.executor = RemediationExecutor(self.runner, self.security, dry_run=self.config.get("dry_run", True))
        self.llm = SyntheticLLM(self.config.get("llm_personas"))

    # ------------------------------------------------------------------
    def _load_config(self, path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def _detect_context(self, namespace: Optional[str] = None) -> ClusterContext:
        context_name = self._current_context_name()
        namespaces = self._available_namespaces()
        namespace = namespace or self.config.get("default_namespace") or namespaces[0] if namespaces else "default"
        roles = self.config.get("rbac_roles", [])
        topology = self._topology_snapshot(namespace)
        return ClusterContext(
            name=context_name or "unknown",
            namespace=namespace,
            user=self.config.get("default_user"),
            available_namespaces=namespaces,
            rbac_roles=roles,
            topology=topology,
        )

    def _current_context_name(self) -> Optional[str]:
        try:
            completed = subprocess.run(
                ["kubectl", "config", "current-context"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except FileNotFoundError:
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip()

    def _available_namespaces(self) -> List[str]:
        try:
            result = self.runner.run("get", "ns", "-o", "json")
        except ValueError:
            return []
        if result.returncode != 0:
            return []
        data = result.json or {}
        return [item.get("metadata", {}).get("name", "default") for item in data.get("items", [])]

    def _topology_snapshot(self, namespace: str) -> Dict[str, List[str]]:
        try:
            pods = self.runner.run("get", "pods", "-o", "json", namespace=namespace)
        except ValueError:
            return {}
        if pods.returncode != 0 or not pods.json:
            return {}
        topology: Dict[str, List[str]] = {}
        for item in pods.json.get("items", []):
            node = item.get("spec", {}).get("nodeName", "unknown")
            topology.setdefault(node, []).append(item.get("metadata", {}).get("name", "pod"))
        return topology

    # ------------------------------------------------------------------
    def process_user_query(self, query: str, namespace: Optional[str] = None) -> Dict[str, Any]:
        self.memory.append({"role": "user", "content": query})
        self.history.append_turn("user", query)

        context = self._detect_context(namespace)
        report = self.validator.validate(context)
        plan = self.executor.build_plan(context, report.issues)

        summary = self.llm.summarise(query, report.issues)
        recommendations = self.llm.recommend(report.issues)
        runbook = self.llm.draft_runbook(report.issues)

        response = {
            "context": context.dict(),
            "summary": summary,
            "issues": [issue.dict() for issue in report.issues],
            "recommendations": recommendations,
            "execution_plan": plan.dict(),
            "runbook": runbook.dict(),
        }

        self.memory.append({"role": "assistant", "content": summary})
        self.history.append_turn("assistant", summary, {"issues": [issue.identifier for issue in report.issues]})

        audit_record = AuditRecord(
            event_id=self.history.new_event_id(),
            actor=self.config.get("agent_name", "k-agent"),
            action="diagnostic_run",
            status="completed",
            metadata={
                "issue_count": len(report.issues),
                "query": query,
                "plan_id": plan.plan_id,
            },
        )
        self.history.record_audit(audit_record)

        logger.info("Processed query '%s' with %d issues detected", query, len(report.issues))
        return response

    def approve_and_execute(self, plan_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        plan = ExecutionPlan.parse_obj(plan_data)
        if self.security.require_additional_approval(plan):
            raise PermissionError("Plan requires multi-level approval")
        plan = self.security.approve_plan(plan, approver=self.config.get("agent_name", "k-agent"))
        outcomes = self.executor.execute(plan)
        return [outcome.dict() for outcome in outcomes]

    def recent_activity(self) -> List[Dict[str, Any]]:
        return [record.dict() for record in self.history.recent_audit()]
