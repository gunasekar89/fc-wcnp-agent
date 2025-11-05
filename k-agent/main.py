"""CLI entrypoint for K-Agent."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from .agent_core import AgentCore

console = Console()
logging.basicConfig(level=logging.INFO)


def render_issues(payload: dict) -> None:
    issues = payload.get("issues", [])
    if not issues:
        console.print("[green]No issues detected.[/green]")
        return
    table = Table(title="Diagnostic Issues", show_lines=True)
    table.add_column("Severity")
    table.add_column("Title")
    table.add_column("Category")
    table.add_column("Recommendation")
    for issue in issues:
        table.add_row(
            issue.get("severity", "info"),
            issue.get("title", ""),
            issue.get("category", ""),
            issue.get("recommendation", "n/a"),
        )
    console.print(table)


def interactive_shell(agent: AgentCore, namespace: Optional[str]) -> None:
    console.print("[bold cyan]Welcome to K-Agent — your Kubernetes SRE co-pilot.[/bold cyan]")
    console.print("Type 'exit' to leave the session.\n")
    while True:
        query = console.input("[bold green]You> [/bold green]")
        if query.lower() in {"exit", "quit"}:
            break
        payload = agent.process_user_query(query, namespace=namespace)
        console.print(f"[yellow]Summary:[/yellow] {payload['summary']}")
        render_issues(payload)
        console.print("[cyan]Recommendations:[/cyan]")
        for rec in payload.get("recommendations", []):
            console.print(f" - {rec}")
        console.print("[magenta]Execution Plan:[/magenta]")
        console.print_json(json.dumps(payload.get("execution_plan", {})))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the K-Agent CLI")
    parser.add_argument("query", nargs="*", help="Optional one-shot query to execute")
    parser.add_argument("--namespace", help="Target namespace for diagnostics")
    parser.add_argument("--config", help="Path to configuration file", default=None)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config_path = Path(args.config) if args.config else None
    agent = AgentCore(config_path=config_path)

    if args.query:
        query = " ".join(args.query)
        payload = agent.process_user_query(query, namespace=args.namespace)
        console.print(f"[yellow]Summary:[/yellow] {payload['summary']}")
        render_issues(payload)
        console.print("[cyan]Recommendations:[/cyan]")
        for rec in payload.get("recommendations", []):
            console.print(f" - {rec}")
        return

    interactive_shell(agent, namespace=args.namespace)


if __name__ == "__main__":
    main()
