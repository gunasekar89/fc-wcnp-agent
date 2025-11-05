"""Streamlit dashboard for visualising K-Agent diagnostics."""

from __future__ import annotations


import streamlit as st

from ..agent_core import AgentCore

st.set_page_config(page_title="K-Agent Dashboard", layout="wide")
agent = AgentCore()

st.title("K-Agent Observability Dashboard")

query = st.text_input("Describe the issue you are facing:")
namespace = st.text_input("Target namespace", value="default")

if st.button("Run Diagnostics") and query:
    payload = agent.process_user_query(query, namespace=namespace)
    st.subheader("Summary")
    st.write(payload["summary"])

    st.subheader("Issues")
    if payload["issues"]:
        st.json(payload["issues"])
    else:
        st.success("No issues detected")

    st.subheader("Recommendations")
    for rec in payload.get("recommendations", []):
        st.write(f"- {rec}")

    st.subheader("Execution Plan")
    st.json(payload.get("execution_plan", {}))

st.sidebar.header("Recent Activity")
for record in agent.recent_activity():
    st.sidebar.write(record)
