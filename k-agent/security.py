"""Safety and compliance guardrails for K-Agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

import yaml

from .models import ApprovalStatus, ExecutionPlan, RemediationAction

logger = logging.getLogger(__name__)


@dataclass
class SafetyRule:
    name: str
    description: str
    forbidden_resources: Iterable[str]
    require_multi_approval: bool = False


class SecurityManager:
    """Validates remediation plans against safety policies."""

    def __init__(self, rules_file: Optional[Path] = None) -> None:
        self.rules_file = rules_file
        self.rules = list(self._load_rules())

    def _load_rules(self) -> Iterable[SafetyRule]:
        if not self.rules_file or not self.rules_file.exists():
            logger.debug("No safety rules file provided; using defaults")
            yield SafetyRule("default", "Baseline resource guard", ["nodes", "namespaces"], True)
            return
        with self.rules_file.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        for item in data.get("rules", []):
            yield SafetyRule(
                name=item.get("name", "unnamed"),
                description=item.get("description", ""),
                forbidden_resources=item.get("forbidden_resources", []),
                require_multi_approval=item.get("require_multi_approval", False),
            )

    # ------------------------------------------------------------------
    def evaluate_plan(self, plan: ExecutionPlan) -> Dict[str, str]:
        """Return a mapping of warnings keyed by action id."""

        warnings: Dict[str, str] = {}
        for action in plan.actions:
            for rule in self.rules:
                if any(resource in (action.command or "") for resource in rule.forbidden_resources):
                    warnings[action.action_id] = (
                        f"Action interacts with protected resource ({', '.join(rule.forbidden_resources)})."
                    )
                    if rule.require_multi_approval:
                        warnings[action.action_id] += " Multi-level approval required."
        return warnings

    def require_additional_approval(self, plan: ExecutionPlan) -> bool:
        """Check if any safety rule requires multi-level approval."""

        for action in plan.actions:
            for rule in self.rules:
                if rule.require_multi_approval and any(
                    resource in (action.command or "") for resource in rule.forbidden_resources
                ):
                    return True
        return False

    def approve_plan(self, plan: ExecutionPlan, approver: str, notes: str | None = None) -> ExecutionPlan:
        logger.info("Plan %s approved by %s", plan.plan_id, approver)
        plan.approval_status = ApprovalStatus.APPROVED
        return plan

    def reject_plan(self, plan: ExecutionPlan, approver: str, reason: str) -> ExecutionPlan:
        logger.warning("Plan %s rejected by %s: %s", plan.plan_id, approver, reason)
        plan.approval_status = ApprovalStatus.REJECTED
        return plan

    def preflight_checks(self, action: RemediationAction) -> bool:
        """Perform non-invasive checks before executing an action."""

        if not action.command:
            logger.debug("Action %s has no command; skipping preflight", action.action_id)
            return True
        prohibited = {"delete namespace", "delete node"}
        for keyword in prohibited:
            if keyword in action.command:
                logger.error("Action %s failed preflight due to prohibited keyword %s", action.action_id, keyword)
                return False
        return True
