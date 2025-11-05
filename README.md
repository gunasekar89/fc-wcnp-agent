# K-Agent - Advanced Kubernetes Troubleshooting Co-Pilot

K-Agent is an AI-assisted Site Reliability Engineering (SRE) companion for Kubernetes
clusters. It combines curated diagnostics, intelligent reasoning, and guarded
automation workflows to help teams detect and remediate production incidents
quickly.

## Features

- **Context awareness**: Automatically detects current cluster context, available
  namespaces, and RBAC profile before running checks.
- **Deep diagnostics**: Runs dozens of pod, network, storage, operator, and
  observability checks to produce actionable findings.
- **LLM-assisted reasoning**: Summarises complex incidents, recommends fixes, and
  drafts runbooks using Kubernetes-focused prompt templates.
- **Safe remediation**: Generates multi-step execution plans with dry-run
  validation, rollback strategies, and approval workflows.
- **Extensible interfaces**: Includes a CLI, FastAPI service, webhook endpoints,
  and a Streamlit dashboard for visual insights.

## Getting Started

1. **Install dependencies**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r k-agent/requirements.txt
   ```

2. **Configure access**

   - Copy `.env.example` to `.env` and populate secrets (API keys, cluster
     endpoints).
   - Update `k-agent/config/config.yaml` to match your namespaces and storage
     preferences.

3. **Run the CLI**

   ```bash
   python -m k-agent.main "Investigate payment service latency"
   ```

4. **Start the API server**

   ```bash
   uvicorn k-agent.api.fastapi_server:app --reload
   ```

5. **Launch the dashboard**

   ```bash
   streamlit run k-agent/dashboard/streamlit_app.py
   ```

## Project Layout

```
k-agent/
├── main.py
├── agent_core.py
├── kubectl_runner.py
├── validator.py
├── executor.py
├── security.py
├── models.py
├── config/
│   ├── config.yaml
│   └── safety_rules.yaml
├── storage/
│   ├── history_manager.py
│   └── sqlite_db.py
├── api/
│   ├── fastapi_server.py
│   └── webhook_handler.py
├── dashboard/
│   └── streamlit_app.py
├── requirements.txt
└── .env.example
```

## Safety & Compliance

- All mutating actions require approval and can be executed in dry-run mode.
- Built-in safety rules prevent disruptive operations on critical namespaces and
  node resources.
- Every diagnostic session is recorded in an audit trail backed by SQLite for
  traceability.

## Roadmap

- Integrate real LLM providers via pluggable adapters
- Expand diagnostics with Prometheus, Loki, and tracing data sources
- Deliver predictive scaling recommendations using historical trends
- Provide GitOps-aware drift detection and automated reconciliation reports
