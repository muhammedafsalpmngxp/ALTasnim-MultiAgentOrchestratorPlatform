"""Shared test kit. Every agent team uses it so its agent plugs into the orchestrator."""

from utils.testing.contract import assert_agent_contract, run_agent_graph
from utils.testing.stub_agent import build_stub_agent

__all__ = ["assert_agent_contract", "build_stub_agent", "run_agent_graph"]
