r"""verifier graph: does the answer match the user's question? (question + answer only: no sources, no fact checking)

    START -> collect -> rules (no LLM)  --+
                    \-> judge (one LLM) --+-> verdict -> END

collect takes the question (``params.request``) and the answer (``params.answer_step``); rules and judge run in
parallel; verdict combines them into the result (card.VerifyResult).
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from utils import AgentInput, AgentOutput, RequestContext
from verifier_agent.nodes.collect import collect
from verifier_agent.nodes.judge import judge
from verifier_agent.nodes.rules import rules
from verifier_agent.nodes.verdict import verdict
from verifier_agent.state import State


def build_graph():
    builder = StateGraph(State, input_schema=AgentInput, output_schema=AgentOutput, context_schema=RequestContext)
    builder.add_node("collect", collect)
    builder.add_node("rules", rules)
    builder.add_node("judge", judge)
    builder.add_node("verdict", verdict)
    builder.add_edge(START, "collect")
    builder.add_edge("collect", "rules")
    builder.add_edge("collect", "judge")
    builder.add_edge(["rules", "judge"], "verdict")  # waits for both
    builder.add_edge("verdict", END)
    return builder.compile(name="verifier")


graph = build_graph()
