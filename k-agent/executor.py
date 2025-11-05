"""Automated remediation execution for K-Agent."""

from __future__ import annotations

import datetime as dt
import logging
import time
import uuid
from typing import Iterable, List

from .kubectl_runner import KubectlRunner
from .models import ActionOutcome, ExecutionPlan, RemediationAction, DiagnosticIssue
from .security import SecurityManager

logger = logging.getLogger(__name__)


class RemediationExecutor:
    """Handles execution lifecycle for remediation plans."""

    def __init__(self, runner: KubectlRunner, security: SecurityManager, dry_run: bool = True) -> None:
        self.runner = runner
        self.security = security
        self.dry_run = dry_run

    def execute(self, plan: ExecutionPlan) -> List[ActionOutcome]:
        from .models import ApprovalStatus

        if plan.approval_status != ApprovalStatus.APPROVED:
            raise PermissionError("Execution plan must be approved before execution")

        outcomes: List[ActionOutcome] = []
        for action in plan.actions:
            if not self.security.preflight_checks(action):
                outcomes.append(ActionOutcome(action_id=action.action_id, success=False, stderr="Preflight failed"))
                continue
            outcome = self._execute_action(action)
            outcomes.append(outcome)
        return outcomes

    def _execute_action(self, action: RemediationAction) -> ActionOutcome:
        logger.info("Executing remediation action %s", action.action_id)
        outcome = ActionOutcome(action_id=action.action_id, success=False)
        start = time.time()

        if action.dry_run_command:
            logger.debug("Performing dry-run command for %s", action.action_id)
            dry_result = self.runner.run(*action.dry_run_command.split())
            outcome.stdout = (outcome.stdout or "") + f"Dry-run output:\n{dry_result.stdout}\n"
            outcome.stderr = (outcome.stderr or "") + dry_result.stderr
            if dry_result.returncode != 0:
                outcome.stderr = (outcome.stderr or "") + "Dry-run failed; aborting execution."
                return outcome

        if self.dry_run or not action.command:
            outcome.success = True
            outcome.stdout = (outcome.stdout or "") + "Dry-run mode: no mutation executed."
        else:
            command_tokens = action.command.split()
            try:
                result = self.runner.run(*command_tokens)
                outcome.stdout = (outcome.stdout or "") + result.stdout
                outcome.stderr = (outcome.stderr or "") + result.stderr
                outcome.success = result.returncode == 0
            except ValueError as exc:
                outcome.stderr = (outcome.stderr or "") + str(exc)
                outcome.success = False
        elapsed = time.time() - start
        outcome.finished_at = outcome.started_at + dt.timedelta(seconds=elapsed)
        return outcome

    def build_plan(self, context, issues: Iterable[DiagnosticIssue]) -> ExecutionPlan:
        actions: List[RemediationAction] = []
        for issue in issues:
            if "CPU" in issue.title or "throttling" in issue.description.lower():
                actions.append(
                    RemediationAction(
                        action_id=str(uuid.uuid4()),
                        title="Increase CPU limits",
                        description="Suggest increasing CPU limits to alleviate throttling.",
                        command="kubectl patch deployment payment-service --type merge --patch-file cpu_patch.yaml",
                        dry_run_command="kubectl get deployment payment-service",
                        requires_approval=True,
                        metadata={"source_issue": issue.identifier},
                    )
                )
        return ExecutionPlan(plan_id=str(uuid.uuid4()), context=context, actions=actions, rollback_plan="kubectl rollout undo")
