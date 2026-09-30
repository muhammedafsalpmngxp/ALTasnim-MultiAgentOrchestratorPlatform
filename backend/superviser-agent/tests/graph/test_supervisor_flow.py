"""The supervisor controls the whole flow: question -> rag | web_search -> verifier -> synthesizer -> answer.
Every node is a LangGraph agent (in-process stub graphs here, their own deployments in production)."""

import uuid

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from orchestrator_agent.clients import LocalAgentClient
from orchestrator_agent.deps import Deps
from orchestrator_agent.graph import build_graph
from orchestrator_agent.planning.policies import enforce_policies
from orchestrator_agent.planning.rule_planner import RulePlanner
from orchestrator_agent.registry import AgentEntry, AgentRegistry
from orchestrator_agent.settings import Policies
from typing_extensions import TypedDict
from verifier_agent.card import CARD as VERIFIER
from web_search_agent.card import CARD as SEARCH

from utils import AgentCard, Plan, Step
from utils.testing import build_stub_agent

QUESTION_SCHEMA = {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}
RAG = AgentCard(name="rag", version="1.0.0", description="document passages", when_to_use="the user's documents",
                when_not_to_use="the web", params_schema=QUESTION_SCHEMA)
SYNTH = AgentCard(name="synthesizer", version="1.0.0", description="final answer", when_to_use="last step",
                  when_not_to_use="finding facts", params_schema=QUESTION_SCHEMA)
CARDS = {"rag": RAG, "web_search": SEARCH, "verifier": VERIFIER, "synthesizer": SYNTH}


def planner_steps(request, feedback=()):
    d = RulePlanner().decide(request, [], CARDS, {}, list(feedback))
    return [(s.id, s.agent, s.depends_on) for s in d.plan.steps]


def test_document_question_goes_to_rag_web_question_to_web_search():
    assert planner_steps("Who issues the pegging sheet?") == [("s1", "rag", []), ("s2", "synthesizer", ["s1"])]
    assert planner_steps("What is the price of iPhone?") == [("s1", "web_search", []), ("s2", "synthesizer", ["s1"])]
    # rag found nothing before: the replan uses the web
    assert planner_steps("Who issues the pegging sheet?", ["step s1 (rag) failed: no passage"])[0][1] == "web_search"


def test_verifier_checks_the_facts_before_the_synthesizer_and_passes_its_verdict():
    plan = Plan(goal="q", steps=[Step(id="s1", agent="rag", objective="find", params={"question": "q"}),
                                 Step(id="s2", agent="synthesizer", objective="answer", params={"question": "q"},
                                      depends_on=["s1"])])
    steps = {s.id: s for s in enforce_policies(plan, CARDS, Policies()).steps}
    assert (steps["v_s2"].agent, steps["v_s2"].depends_on) == ("verifier", ["s1"])
    assert steps["s2"].depends_on == ["s1", "v_s2"]
    assert "v_final" not in steps


class _Io(TypedDict, total=False):
    task: dict
    result: dict


def recording_agent(name, reply, seen):
    """A LangGraph agent with the platform contract that records the task it got."""

    def run(state: _Io) -> dict:
        seen.append((name, state["task"]))
        return {"result": reply(state["task"])}

    builder = StateGraph(_Io)
    builder.add_node("run", run)
    builder.add_edge(START, "run")
    builder.add_edge("run", END)
    return builder.compile(name=name)


def make_graph(rag_chunks, passages_answer=True):
    """``passages_answer=False``: the verifier rejects rag's passages (they do not answer the question)."""
    seen = []

    def rag(task):
        if not rag_chunks:
            return {"status": "failed", "summary": "No passage in the documents matches the question", "chunks": []}
        return {"status": "ok", "question": task["params"]["question"], "chunks": rag_chunks}  # like Rag: no summary

    def synthesizer(task):
        return {"status": "ok", "summary": "PDO", "answer": "The sheet is issued by **PDO**."}

    def verifier(task):
        from_rag = any("chunks" in out for out in task["inputs"].values())
        if from_rag and not passages_answer:
            return {"status": "failed", "summary": "Verification failed: s1: content does not answer the question"}
        return {"status": "ok", "summary": "Verification passed"}

    def entry(name, graph, card):
        return AgentEntry(name, LocalAgentClient(graph), card, fetched_at=float("inf"))

    registry = AgentRegistry({
        "rag": entry("rag", recording_agent("rag", rag, seen), RAG),
        "web_search": entry("web_search", build_stub_agent("web_search", {"status": "ok", "summary": "web: PDO"}),
                            SEARCH),
        "verifier": entry("verifier", recording_agent("verifier", verifier, seen), VERIFIER),
        "synthesizer": entry("synthesizer", recording_agent("synthesizer", synthesizer, seen), SYNTH),
    })
    deps = Deps(registry=registry, planner=RulePlanner(), policies=Policies())
    return build_graph(deps=deps, checkpointer=InMemorySaver()), seen


async def test_supervisor_runs_rag_then_verifier_then_synthesizer():
    graph, seen = make_graph([{"content": "PDO issues the pegging sheet", "document_name": "rules.pdf"}])
    assert {"rag", "web_search", "verifier", "synthesizer"} <= set(graph.get_graph().nodes)

    out = await graph.ainvoke({"request": "Who issues the pegging sheet?"},
                              {"configurable": {"thread_id": str(uuid.uuid4())}})

    assert out["final"] == "The sheet is issued by **PDO**."
    assert [name for name, _ in seen] == ["rag", "verifier", "synthesizer"]
    synth = seen[2][1]
    assert synth["params"]["question"] == "Who issues the pegging sheet?"
    assert set(synth["inputs"]) == {"s1", "v_s2"}  # the passages and the verdict
    assert synth["inputs"]["s1"]["chunks"][0]["document_name"] == "rules.pdf"


async def test_nothing_in_the_documents_falls_back_to_the_web():
    graph, seen = make_graph([])
    out = await graph.ainvoke({"request": "Who issues the pegging sheet?"},
                              {"configurable": {"thread_id": str(uuid.uuid4())}})

    assert out["final"] == "The sheet is issued by **PDO**."
    assert [name for name, _ in seen] == ["rag", "verifier", "synthesizer"]  # rag failed: no verification needed
    assert out["results"]["s1"]["agent"] == "web_search"  # the replan
    assert seen[2][1]["inputs"]["s1"]["summary"] == "web: PDO"


async def test_rag_passages_that_fail_verification_are_replaced_by_the_web_then_verified_again():
    graph, seen = make_graph([{"content": "Unrelated clause", "document_name": "rules.pdf"}], passages_answer=False)
    out = await graph.ainvoke({"request": "Who issues the pegging sheet?"},
                              {"configurable": {"thread_id": str(uuid.uuid4())}})

    assert out["final"] == "The sheet is issued by **PDO**."
    # rag -> verifier rejects it -> web_search -> verifier passes -> synthesizer
    assert [name for name, _ in seen] == ["rag", "verifier", "verifier", "synthesizer"]
    assert out["results"]["s1"]["agent"] == "web_search"  # rag's rejected s1 was redone, not reused
    assert any("(rag) failed verification" in f for f in out["feedback"])
    synth = seen[3][1]["inputs"]
    assert synth["s1"]["summary"] == "web: PDO" and synth["v_s2"]["summary"] == "Verification passed"


def test_any_request_is_a_question_only_small_talk_is_answered_directly():
    assert planner_steps("flaf and pegg") == [("s1", "rag", []), ("s2", "synthesizer", ["s1"])]
    assert planner_steps("retention money") == [("s1", "rag", []), ("s2", "synthesizer", ["s1"])]
    for small_talk in ("hello", "Hi!", "thanks", "what can you do?"):
        d = RulePlanner().decide(small_talk, [], CARDS, {}, [])
        assert d.action == "answer" and "documents" in d.answer and "email" not in d.answer
