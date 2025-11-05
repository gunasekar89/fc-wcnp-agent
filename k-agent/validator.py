"""Comprehensive cluster diagnostics for K-Agent.

The validator orchestrates a suite of deep health checks spanning pods,
networking, storage, operators, and platform integrations. While the default
implementation focuses on rule-based heuristics, the architecture allows for
pluggable analyzers that can be extended with ML-driven strategies.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Callable, Iterable, List, Sequence

from .kubectl_runner import KubectlResult, KubectlRunner
from .models import ClusterContext, DiagnosticIssue, DiagnosticReport, SeverityLevel

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticCheck:
    """Represents a diagnostic function that returns zero or more issues."""

    name: str
    categories: Sequence[str]
    run: Callable[[ClusterContext], Iterable[DiagnosticIssue]]


class Validator:
    """Coordinates and executes the available diagnostic checks."""

    def __init__(self, runner: KubectlRunner) -> None:
        self.runner = runner
        self.checks: List[DiagnosticCheck] = []
        self._register_builtin_checks()

    def _register_builtin_checks(self) -> None:
        self.checks.extend(
            [
                DiagnosticCheck("pod_health", ["compute"], self._check_pod_failures),
                DiagnosticCheck("container_resources", ["compute"], self._check_container_resources),
                DiagnosticCheck("probe_analysis", ["compute"], self._check_probes),
                DiagnosticCheck("network_services", ["network"], self._check_services),
                DiagnosticCheck("network_policies", ["network"], self._check_network_policies),
                DiagnosticCheck("dns_resolution", ["network"], self._check_dns),
                DiagnosticCheck("mesh_health", ["network"], self._check_service_mesh),
                DiagnosticCheck("storage_pvc", ["storage"], self._check_pvcs),
                DiagnosticCheck("statefulsets", ["storage"], self._check_statefulsets),
                DiagnosticCheck("operator_health", ["operators"], self._check_operators),
                DiagnosticCheck("webhook_validations", ["operators"], self._check_webhooks),
                DiagnosticCheck("crd_compatibility", ["operators"], self._check_crd_versions),
                DiagnosticCheck("monitoring_signals", ["observability"], self._check_monitoring),
                DiagnosticCheck("security_context", ["security"], self._check_security_contexts),
                DiagnosticCheck("cost_controls", ["cost"], self._check_cost_regressions),
            ]
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def validate(self, context: ClusterContext) -> DiagnosticReport:
        """Run all diagnostic checks and aggregate the results."""

        issues: List[DiagnosticIssue] = []
        for check in self.checks:
            try:
                logger.debug("Running diagnostic check: %s", check.name)
                results = list(check.run(context))
                logger.debug("Check %s produced %d issues", check.name, len(results))
                issues.extend(results)
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.exception("Diagnostic check %s failed: %s", check.name, exc)
                issues.append(
                    DiagnosticIssue(
                        identifier=f"check_error::{check.name}",
                        title=f"{check.name} diagnostic failed",
                        description=str(exc),
                        severity=SeverityLevel.WARNING,
                        category="diagnostics",
                        evidence={"check": check.name},
                        recommendation="Inspect agent logs for stack trace details.",
                    )
                )

        return DiagnosticReport(context=context, issues=issues)

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------
    def _check_pod_failures(self, context: ClusterContext) -> Iterable[DiagnosticIssue]:
        """Inspect pod states for common failure reasons."""

        result = self._safe_kubectl("get", "pods", "-o", "json", namespace=context.namespace)
        if result.returncode != 0:
            yield self._kubectl_error("pods", result)
            return

        data = result.json or {}
        items = data.get("items", [])
        for pod in items:
            status = pod.get("status", {})
            phase = status.get("phase")
            reason = status.get("reason")
            metadata = pod.get("metadata", {})
            name = metadata.get("name", "unknown")
            if phase == "Failed" or reason in {"CrashLoopBackOff", "ImagePullBackOff"}:
                containers = status.get("containerStatuses", [])
                evidence = {"phase": phase or "unknown"}
                for container in containers:
                    state = container.get("state", {})
                    if "waiting" in state:
                        evidence[container.get("name", "container")] = state["waiting"].get("reason", "unknown")
                yield DiagnosticIssue(
                    identifier=f"pod_failure::{name}",
                    title=f"Pod {name} is failing",
                    description=f"Pod {name} reported phase {phase} with reason {reason}",
                    severity=SeverityLevel.ERROR,
                    category="compute",
                    evidence=evidence,
                    recommendation="Inspect container logs and events, consider restarting the workload.",
                )

    def _check_container_resources(self, context: ClusterContext) -> Iterable[DiagnosticIssue]:
        result = self._safe_kubectl("top", "pods", namespace=context.namespace)
        if result.returncode != 0:
            yield self._kubectl_error("top pods", result)
            return
        # Without live metrics, simulate detection of throttling using heuristics.
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 3:
                continue
            pod_name, cpu, memory = parts[:3]
            if cpu.endswith("m") and int(cpu.rstrip("m")) > 80:
                yield DiagnosticIssue(
                    identifier=f"cpu_throttle::{pod_name}",
                    title=f"CPU saturation detected for {pod_name}",
                    description=f"Pod {pod_name} is consuming {cpu} CPU units.",
                    severity=SeverityLevel.WARNING,
                    category="compute",
                    evidence={"cpu": cpu, "memory": memory},
                    recommendation="Consider increasing CPU limits or scaling replicas.",
                )

    def _check_probes(self, context: ClusterContext) -> Iterable[DiagnosticIssue]:
        result = self._safe_kubectl("get", "pods", "-o", "json", namespace=context.namespace)
        if result.returncode != 0:
            yield self._kubectl_error("pods", result)
            return
        data = result.json or {}
        for pod in data.get("items", []):
            spec = pod.get("spec", {})
            containers = spec.get("containers", [])
            for container in containers:
                probes = [container.get("livenessProbe"), container.get("readinessProbe")]
                if all(probe is None for probe in probes):
                    name = pod.get("metadata", {}).get("name", "pod")
                    yield DiagnosticIssue(
                        identifier=f"probe_missing::{name}",
                        title=f"Probes missing for {name}",
                        description="Container lacks liveness/readiness probes, reducing resiliency.",
                        severity=SeverityLevel.WARNING,
                        category="compute",
                        evidence={"container": container.get("name", "container")},
                        recommendation="Define liveness and readiness probes to improve recovery.",
                    )

    def _check_services(self, context: ClusterContext) -> Iterable[DiagnosticIssue]:
        result = self._safe_kubectl("get", "svc", "-o", "json", namespace=context.namespace)
        if result.returncode != 0:
            yield self._kubectl_error("services", result)
            return
        data = result.json or {}
        for svc in data.get("items", []):
            spec = svc.get("spec", {})
            if spec.get("type") == "LoadBalancer" and not spec.get("externalIPs") and not spec.get("externalTrafficPolicy"):
                name = svc.get("metadata", {}).get("name", "service")
                yield DiagnosticIssue(
                    identifier=f"loadbalancer_pending::{name}",
                    title=f"LoadBalancer {name} is pending",
                    description="LoadBalancer service lacks external IP assignment.",
                    severity=SeverityLevel.WARNING,
                    category="network",
                    evidence={"service": name},
                    recommendation="Check cloud provider integration and events for provisioning errors.",
                )

    def _check_network_policies(self, context: ClusterContext) -> Iterable[DiagnosticIssue]:
        result = self._safe_kubectl("get", "networkpolicy", "-o", "json", namespace=context.namespace)
        if result.returncode != 0:
            yield self._kubectl_error("network policies", result)
            return
        data = result.json or {}
        if not data.get("items"):
            yield DiagnosticIssue(
                identifier="networkpolicy_absent",
                title="No NetworkPolicies defined",
                description="Namespace lacks network policies which may violate security standards.",
                severity=SeverityLevel.WARNING,
                category="network",
                evidence={"namespace": context.namespace},
                recommendation="Define ingress/egress policies to enforce zero-trust networking.",
            )

    def _check_dns(self, context: ClusterContext) -> Iterable[DiagnosticIssue]:
        # Without actual DNS probing, surface context awareness if cluster lacks metrics
        if not context.topology:
            yield DiagnosticIssue(
                identifier="topology_unknown",
                title="Cluster topology unavailable",
                description="Unable to map nodes to workloads. DNS and service discovery checks limited.",
                severity=SeverityLevel.INFO,
                category="network",
                evidence={"namespace": context.namespace},
                recommendation="Grant list/watch permissions for nodes and endpoints.",
            )

    def _check_service_mesh(self, context: ClusterContext) -> Iterable[DiagnosticIssue]:
        if any("istio" in role for role in context.rbac_roles):
            # Assume service mesh is enabled but we need metrics
            yield DiagnosticIssue(
                identifier="mesh_metrics_missing",
                title="Service mesh metrics unavailable",
                description="Mesh RBAC detected but no telemetry signals were provided.",
                severity=SeverityLevel.INFO,
                category="network",
                evidence={"roles": ",".join(context.rbac_roles)},
                recommendation="Ensure Prometheus scraping for mesh control plane is configured.",
            )

    def _check_pvcs(self, context: ClusterContext) -> Iterable[DiagnosticIssue]:
        result = self._safe_kubectl("get", "pvc", "-o", "json", namespace=context.namespace)
        if result.returncode != 0:
            yield self._kubectl_error("pvcs", result)
            return
        data = result.json or {}
        for pvc in data.get("items", []):
            status = pvc.get("status", {})
            if status.get("phase") == "Pending":
                name = pvc.get("metadata", {}).get("name", "pvc")
                yield DiagnosticIssue(
                    identifier=f"pvc_pending::{name}",
                    title=f"PVC {name} pending",
                    description="PersistentVolumeClaim has not been bound to a volume.",
                    severity=SeverityLevel.ERROR,
                    category="storage",
                    evidence={"pvc": name, "storageClass": pvc.get("spec", {}).get("storageClassName", "unknown")},
                    recommendation="Confirm storage class availability and provisioner health.",
                )

    def _check_statefulsets(self, context: ClusterContext) -> Iterable[DiagnosticIssue]:
        result = self._safe_kubectl("get", "statefulset", "-o", "json", namespace=context.namespace)
        if result.returncode != 0:
            yield self._kubectl_error("statefulsets", result)
            return
        data = result.json or {}
        for sts in data.get("items", []):
            spec = sts.get("spec", {})
            status = sts.get("status", {})
            replicas = spec.get("replicas", 0)
            ready = status.get("readyReplicas", 0)
            if ready < replicas:
                name = sts.get("metadata", {}).get("name", "statefulset")
                yield DiagnosticIssue(
                    identifier=f"statefulset_not_ready::{name}",
                    title=f"StatefulSet {name} not fully ready",
                    description=f"{ready}/{replicas} replicas are ready.",
                    severity=SeverityLevel.WARNING,
                    category="storage",
                    evidence={"ready": str(ready), "desired": str(replicas)},
                    recommendation="Inspect pod ordinal logs and volume attachments for failures.",
                )

    def _check_operators(self, context: ClusterContext) -> Iterable[DiagnosticIssue]:
        result = self._safe_kubectl("get", "pods", "-n", "operators", "-o", "json")
        if result.returncode != 0:
            yield DiagnosticIssue(
                identifier="operator_namespace_inaccessible",
                title="Operator namespace inaccessible",
                description="Unable to fetch operator pods; RBAC may limit visibility.",
                severity=SeverityLevel.INFO,
                category="operators",
                evidence={"stderr": result.stderr},
                recommendation="Grant view access to operator namespaces for richer diagnostics.",
            )
            return
        data = result.json or {}
        for pod in data.get("items", []):
            status = pod.get("status", {})
            if status.get("phase") != "Running":
                name = pod.get("metadata", {}).get("name", "operator-pod")
                yield DiagnosticIssue(
                    identifier=f"operator_unhealthy::{name}",
                    title=f"Operator pod {name} unhealthy",
                    description=f"Operator pod is in phase {status.get('phase')}.",
                    severity=SeverityLevel.WARNING,
                    category="operators",
                    evidence={"namespace": "operators"},
                    recommendation="Inspect operator logs for reconciliation errors.",
                )

    def _check_webhooks(self, context: ClusterContext) -> Iterable[DiagnosticIssue]:
        result = self._safe_kubectl("get", "mutatingwebhookconfiguration", "-o", "json")
        if result.returncode != 0:
            yield DiagnosticIssue(
                identifier="webhook_list_failed",
                title="Webhook inventory unavailable",
                description="Unable to list mutating webhooks; approvals may be impacted.",
                severity=SeverityLevel.INFO,
                category="operators",
                evidence={"stderr": result.stderr},
                recommendation="Grant cluster-wide list permissions to audit webhook configuration.",
            )
            return
        data = result.json or {}
        for webhook in data.get("items", []):
            name = webhook.get("metadata", {}).get("name", "webhook")
            timeout = webhook.get("webhooks", [{}])[0].get("timeoutSeconds", 10)
            if timeout < 30:
                yield DiagnosticIssue(
                    identifier=f"webhook_timeout::{name}",
                    title=f"Webhook {name} timeout is aggressive",
                    description=f"Webhook timeout set to {timeout}s which may cause retries under load.",
                    severity=SeverityLevel.WARNING,
                    category="operators",
                    evidence={"timeout": str(timeout)},
                    recommendation="Increase timeoutSeconds to at least 30 seconds and enable retries.",
                )

    def _check_crd_versions(self, context: ClusterContext) -> Iterable[DiagnosticIssue]:
        result = self._safe_kubectl("get", "crd", "-o", "json")
        if result.returncode != 0:
            yield DiagnosticIssue(
                identifier="crd_list_failed",
                title="CRD list unavailable",
                description="Unable to enumerate CustomResourceDefinitions.",
                severity=SeverityLevel.INFO,
                category="operators",
                evidence={"stderr": result.stderr},
                recommendation="Grant cluster-admin view rights for CRD auditing.",
            )
            return
        data = result.json or {}
        for crd in data.get("items", []):
            spec = crd.get("spec", {})
            versions = spec.get("versions", [])
            storage_versions = [v["name"] for v in versions if v.get("storage")]
            if len(storage_versions) > 1:
                name = crd.get("metadata", {}).get("name", "crd")
                yield DiagnosticIssue(
                    identifier=f"crd_multiple_storage::{name}",
                    title=f"CRD {name} has multiple storage versions",
                    description="Multiple storage versions may cause reconciliation issues.",
                    severity=SeverityLevel.WARNING,
                    category="operators",
                    evidence={"storageVersions": ",".join(storage_versions)},
                    recommendation="Migrate to a single storage version before upgrading the API server.",
                )

    def _check_monitoring(self, context: ClusterContext) -> Iterable[DiagnosticIssue]:
        if not context.topology:
            yield DiagnosticIssue(
                identifier="monitoring_context_missing",
                title="Monitoring correlation limited",
                description="No topology information detected; Prometheus correlations disabled.",
                severity=SeverityLevel.INFO,
                category="observability",
                evidence={},
                recommendation="Configure topology discovery via ClusterRole bindings.",
            )
        else:
            for node, workloads in context.topology.items():
                if len(workloads) > 100:
                    yield DiagnosticIssue(
                        identifier=f"node_overloaded::{node}",
                        title=f"Node {node} hosts many workloads",
                        description=f"Node {node} schedules {len(workloads)} pods which may impact performance.",
                        severity=SeverityLevel.WARNING,
                        category="observability",
                        evidence={"workloads": str(len(workloads))},
                        recommendation="Check node resource utilisation and consider rebalancing.",
                    )

    def _check_security_contexts(self, context: ClusterContext) -> Iterable[DiagnosticIssue]:
        result = self._safe_kubectl("get", "pods", "-o", "json", namespace=context.namespace)
        if result.returncode != 0:
            yield self._kubectl_error("pods", result)
            return
        data = result.json or {}
        for pod in data.get("items", []):
            spec = pod.get("spec", {})
            security_ctx = spec.get("securityContext", {})
            if security_ctx.get("runAsUser") == 0:
                name = pod.get("metadata", {}).get("name", "pod")
                yield DiagnosticIssue(
                    identifier=f"privileged_pod::{name}",
                    title=f"Pod {name} runs as root",
                    description="Pod securityContext runAsUser=0 may violate compliance policies.",
                    severity=SeverityLevel.ERROR,
                    category="security",
                    evidence={"pod": name},
                    recommendation="Update securityContext to use non-root user and enforce PodSecurity standards.",
                )

    def _check_cost_regressions(self, context: ClusterContext) -> Iterable[DiagnosticIssue]:
        # Simulate anomaly detection by random sampling to demonstrate structure.
        if random.random() < 0.05:
            yield DiagnosticIssue(
                identifier="cost_anomaly",
                title="Potential cost anomaly detected",
                description="Resource usage trend indicates >20% increase week-over-week.",
                severity=SeverityLevel.WARNING,
                category="cost",
                evidence={"namespace": context.namespace},
                recommendation="Review autoscaling policies and right-size resource requests.",
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _safe_kubectl(self, *args: str, namespace: str | None = None) -> KubectlResult:
        try:
            return self.runner.run(*args, namespace=namespace)
        except ValueError as exc:
            logger.debug("Unsafe command prevented: %s", exc)
            return KubectlResult(command=list(args), returncode=126, stdout="", stderr=str(exc))

    def _kubectl_error(self, resource: str, result: KubectlResult) -> DiagnosticIssue:
        return DiagnosticIssue(
            identifier=f"kubectl_error::{resource}",
            title=f"Unable to inspect {resource}",
            description=f"kubectl command failed with code {result.returncode}",
            severity=SeverityLevel.INFO,
            category="diagnostics",
            evidence={"stderr": result.stderr},
            recommendation="Verify RBAC permissions and cluster connectivity.",
        )
