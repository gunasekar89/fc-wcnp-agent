"""Safe kubectl command execution helpers.

The runner is intentionally conservative: it sanitises commands, enforces
resource guards and captures structured output for downstream reasoning.
"""

from __future__ import annotations

import json
import logging
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class KubectlResult:
    """Captured output from a kubectl invocation."""

    command: List[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def json(self) -> Optional[dict]:
        try:
            return json.loads(self.stdout)
        except json.JSONDecodeError:
            return None


class KubectlRunner:
    """Wraps kubectl execution with safety and observability hooks."""

    SAFE_PREFIXES = {
        "get",
        "describe",
        "logs",
        "top",
        "api-resources",
        "api-versions",
    }

    GUARDED_SUBSTRINGS = {"delete", "cordon", "drain", "taint", "uncordon"}

    def __init__(self, kubeconfig: Optional[Path] = None, dry_run: bool = False) -> None:
        self.kubeconfig = kubeconfig
        self.dry_run = dry_run

    def build_command(self, *args: str, namespace: Optional[str] = None) -> List[str]:
        base = ["kubectl"]
        if self.kubeconfig:
            base.extend(["--kubeconfig", str(self.kubeconfig)])
        if namespace:
            base.extend(["--namespace", namespace])
        base.extend(args)
        return base

    def _is_safe(self, args: Iterable[str]) -> bool:
        if not args:
            return False
        if args[0] not in self.SAFE_PREFIXES:
            return False
        command_str = " ".join(args)
        return not any(token in command_str for token in self.GUARDED_SUBSTRINGS)

    def run(self, *args: str, namespace: Optional[str] = None, timeout: int = 30) -> KubectlResult:
        """Execute a kubectl command, enforcing safety by default."""

        if not self._is_safe(args):
            raise ValueError(f"Unsafe kubectl command requested: {' '.join(args)}")

        command = self.build_command(*args, namespace=namespace)
        logger.debug("Executing kubectl command: %s", shlex.join(command))

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            logger.warning("kubectl not available: %s", exc)
            return KubectlResult(command, returncode=127, stdout="", stderr=str(exc))

        return KubectlResult(command, completed.returncode, completed.stdout, completed.stderr)

    def dry_run_apply(self, manifest: str) -> KubectlResult:
        """Validate an apply operation without mutating the cluster."""

        args = ["apply", "-f", "-"]
        if self.dry_run:
            args.extend(["--dry-run=server"])
        command = self.build_command(*args)
        logger.debug("Validating manifest with dry-run apply")

        try:
            completed = subprocess.run(
                command,
                input=manifest,
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
        except FileNotFoundError as exc:
            logger.warning("kubectl not available for dry-run: %s", exc)
            return KubectlResult(command, 127, "", str(exc))

        return KubectlResult(command, completed.returncode, completed.stdout, completed.stderr)
