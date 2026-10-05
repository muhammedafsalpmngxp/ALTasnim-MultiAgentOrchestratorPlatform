"""The supervisor controls the whole flow through the real orchestrator graph: its decisions (here scripted, in
production its LLM) become the plan, progress runs the plan, and the supervisor reviews on events.
Every agent is a LangGraph agent (in-process stub graphs here, their own deployments in production)."""

import uuid

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from orchestrator_agent.clients import LocalAgentClient
from orchestrator_agent.deps import Deps
from orchestrator_agent.graph import build_graph
from orchestrator_agent.planning.llm_supervisor import LLMSupervisor
from orchestrator_agent.planning.scripted import ScriptedSupervisor
from orchestrator_agent.registry import AgentEntry, AgentRegistry
from orchestrator_agent.settings import Policies
from typing_extensions import TypedDict
from verifier_agent.card import CARD as VERIFIER
from web_search_agent.card import CARD as SEARCH

from utils import AgentCard, Plan, Step, SupervisorDecision
from utils.testing import build_stub_agent

QUESTION_SCHEMA = {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}
RAG = AgentCard(name="rag", version="1.0.0", description="document passages", when_to_use="the user's documents",
                when_not_to_use="the web", role="source", params_schema=QUESTION_SCHEMA)
SYNTH = AgentCard(name="synthesizer", version="1.0.0", description="final answer", when_to_use="last step",
                  when_not_to_use="finding facts", role="final_answer", params_schema=QUESTION_SCHEMA)
TRANSLATOR = AgentCard(name="translator", version="0.1.0", description="Translates text", when_to_use="translate",
                       when_not_to_use="finding facts", role="transform")
QUESTION = "Who issues the pegging sheet?"


def plan(*items: dict) -> SupervisorDecision:
    steps = [Step(**s) for s in items]
    return SupervisorDecision(action="plan", understanding="who issues the sheet", reasoning="scripted",
                              plan=Plan(goal=QUESTION, success_criteria=["the issuer"], steps=steps))


def answer_plan(source: str, ids=("s1", "s2", "s3")) -> SupervisorDecision:
    """source -> verifier -> synthesizer, as the LLM is asked to plan a question."""
    a, v, f = ids
    params = {"question": QUESTION} if source == "rag" else {"query": QUESTION}
    return plan({"id": a, "agent": source, "objective": f"Find who issues the pegging sheet ({source})",
                 "params": params},
                {"id": v, "agent": "verifier", "objective": "Check the facts answer the question", "depends_on": [a]},
                {"id": f, "agent": "synthesizer", "objective": "Answer", "params": {"question": QUESTION},
                 "depends_on": [a, v]})


def docs_then_web(ctx):
    """The documents first; when they fail or are rejected, the web (what the LLM decides from the cards)."""
    if ctx.mode == "plan":
        return answer_plan("rag")
    return answer_plan("web_search", ids=("s4", "s5", "s6"))


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


def make_graph(rag_chunks, script=docs_then_web, passages_answer=True, extra=None, supervisor=None):
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

    entries = {
        "rag": entry("rag", recording_agent("rag", rag, seen), RAG),
        "web_search": entry("web_search", build_stub_agent("web_search", {"status": "ok", "summary": "web: PDO"}),
                            SEARCH),
        "verifier": entry("verifier", recording_agent("verifier", verifier, seen), VERIFIER),
        "synthesizer": entry("synthesizer", recording_agent("synthesizer", synthesizer, seen), SYNTH),
    }
    for name, (card, reply) in (extra or {}).items():
        entries[name] = entry(name, recording_agent(name, reply, seen), card)
    supervisor = supervisor or ScriptedSupervisor(script)
    deps = Deps(registry=AgentRegistry(entries), supervisor=supervisor, policies=Policies())
    return build_graph(deps=deps, checkpointer=InMemorySaver()), seen, supervisor


def new_thread():
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


async def test_the_plan_runs_rag_then_verifier_then_synthesizer_with_one_supervisor_call():
    graph, seen, sup = make_graph([{"content": "PDO issues the pegging sheet", "document_name": "rules.pdf"}])
    assert {"rag", "web_search", "verifier", "synthesizer"} <= set(graph.get_graph().nodes)

    out = await graph.ainvoke({"request": QUESTION}, new_thread())

    assert out["final"] == "The sheet is issued by **PDO**."
    assert [name for name, _ in seen] == ["rag", "verifier", "synthesizer"]
    assert len(sup.calls) == 1 and sup.calls[0].mode == "plan"  # the final answer ran: no review
    assert set(sup.calls[0].cards) == {"rag", "web_search", "verifier", "synthesizer"}
    synth = seen[2][1]
    assert synth["params"]["question"] == QUESTION
    assert set(synth["inputs"]) == {"s1", "s2"}  # the passages and the verdict
    assert synth["inputs"]["s1"]["chunks"][0]["document_name"] == "rules.pdf"
    assert out["plan"]["success_criteria"] == ["the issuer"]


async def test_nothing_in_the_documents_the_supervisor_reviews_and_uses_the_web():
    graph, seen, sup = make_graph([])
    out = await graph.ainvoke({"request": QUESTION}, new_thread())

    assert out["final"] == "The sheet is issued by **PDO**."
    assert [name for name, _ in seen] == ["rag", "verifier", "synthesizer"]  # rag failed: its verifier never ran
    review = sup.calls[1]
    assert (review.mode, review.review_reason) == ("review", "failed")
    assert review.results["s1"]["status"] == "failed"  # the review sees the failure
    assert any("(rag) failed" in f for f in review.feedback)
    assert out["plan"]["version"] == 2 and out["replans"] == 1
    assert set(out["results"]) == {"s4", "s5", "s6"}  # the failed plan's results are gone
    assert seen[2][1]["inputs"]["s4"]["summary"] == "web: PDO"


async def test_passages_rejected_by_the_verifier_are_replaced_by_the_web_then_verified_again():
    graph, seen, sup = make_graph([{"content": "Unrelated clause", "document_name": "rules.pdf"}],
                                  passages_answer=False)
    out = await graph.ainvoke({"request": QUESTION}, new_thread())

    assert out["final"] == "The sheet is issued by **PDO**."
    # rag -> verifier rejects it -> (review) web_search -> verifier passes -> synthesizer
    assert [name for name, _ in seen] == ["rag", "verifier", "verifier", "synthesizer"]
    review = sup.calls[1]
    assert review.results["s1"]["status"] == "failed"  # rejected data is marked, so it is never reused
    assert "failed verification" in review.results["s1"]["error"]
    assert any("(rag) failed verification" in f for f in out["feedback"])


async def test_without_a_final_answer_agent_the_supervisor_reviews_and_writes_the_answer():
    def script(ctx):
        if ctx.mode == "plan":
            return plan({"id": "s1", "agent": "rag", "objective": "find", "params": {"question": QUESTION}},
                        {"id": "s2", "agent": "verifier", "objective": "check", "depends_on": ["s1"]})
        assert ctx.review_reason == "complete" and ctx.results["s1"]["status"] == "ok"
        return SupervisorDecision(action="finish", answer="PDO issues it (rules.pdf).")

    graph, seen, sup = make_graph([{"content": "PDO issues the pegging sheet", "document_name": "rules.pdf"}],
                                  script=script)
    out = await graph.ainvoke({"request": QUESTION}, new_thread())
    assert out["final"] == "PDO issues it (rules.pdf)." and len(sup.calls) == 2


async def test_small_talk_is_answered_without_agents():
    graph, seen, sup = make_graph([], script=lambda ctx: SupervisorDecision(action="answer", answer="Hello!"))
    out = await graph.ainvoke({"request": "hello"}, new_thread())
    assert out["final"] == "Hello!" and seen == [] and out.get("plan") is None


async def test_clarify_asks_the_user_and_plans_with_the_answer():
    def script(ctx):
        if not ctx.clarifications:
            return SupervisorDecision(action="clarify", question="Which document?")
        assert ctx.clarifications == ["rules.pdf"]
        return answer_plan("rag")

    graph, seen, sup = make_graph([{"content": "PDO issues it", "document_name": "rules.pdf"}], script=script)
    cfg = new_thread()
    out = await graph.ainvoke({"request": QUESTION}, cfg)
    assert out["__interrupt__"][0].value == {"kind": "clarification", "question": "Which document?"}
    out = await graph.ainvoke(Command(resume="rules.pdf"), cfg)
    assert out["final"] == "The sheet is issued by **PDO**."


async def test_the_supervisor_stops_after_the_replan_limit():
    def script(ctx):  # keeps trying the documents with a new step id
        n = len(ctx.feedback)
        return plan({"id": f"r{n}", "agent": "rag", "objective": f"try {n}", "params": {"question": QUESTION}})

    graph, seen, sup = make_graph([], script=script)
    out = await graph.ainvoke({"request": QUESTION}, new_thread())
    assert out["replans"] == Policies().max_replans
    assert out["final"].startswith("I could not complete the request")
    assert "No passage in the documents" in out["final"]


async def test_with_no_replan_left_the_supervisor_writes_the_honest_reply():
    def script(ctx):
        if ctx.mode == "review" and ctx.replans_left == 0:
            assert any("No passage in the documents" in f for f in ctx.feedback)
            return SupervisorDecision(action="answer", answer="I could not find it in your documents.")
        n = len(ctx.feedback)
        return plan({"id": f"r{n}", "agent": "rag", "objective": f"try {n}", "params": {"question": QUESTION}})

    graph, seen, sup = make_graph([], script=script)
    out = await graph.ainvoke({"request": QUESTION}, new_thread())
    assert out["final"] == "I could not find it in your documents."
    assert len(sup.calls) == 2 + Policies().max_replans  # the plan, each replan, the reply


async def test_a_new_agent_is_planned_and_run_from_its_card_alone():
    """translator is not known to the supervisor's code: it is a node and the plan can use it."""
    def translate(task):
        return {"status": "ok", "summary": "Arabic: PDO"}

    def script(ctx):
        assert "translator" in ctx.cards
        return plan({"id": "s1", "agent": "rag", "objective": "find", "params": {"question": QUESTION}},
                    {"id": "s2", "agent": "translator", "objective": "Translate to Arabic", "depends_on": ["s1"]},
                    {"id": "s3", "agent": "synthesizer", "objective": "Answer", "params": {"question": QUESTION},
                     "depends_on": ["s2"]})

    graph, seen, sup = make_graph([{"content": "PDO issues it", "document_name": "rules.pdf"}], script=script,
                                  extra={"translator": (TRANSLATOR, translate)})
    assert "translator" in graph.get_graph().nodes
    out = await graph.ainvoke({"request": QUESTION}, new_thread())
    assert [name for name, _ in seen] == ["rag", "translator", "synthesizer"]
    assert seen[1][1]["inputs"]["s1"]["chunks"][0]["content"] == "PDO issues it"
    assert out["final"] == "The sheet is issued by **PDO**."


async def test_each_question_in_a_chat_runs_the_agents_again_and_sees_the_history():
    """A second question on the same thread must not reuse the first question's agent threads (old answers)."""
    graph, seen, sup = make_graph([{"content": "PDO issues the pegging sheet", "document_name": "rules.pdf"}])
    cfg = new_thread()

    await graph.ainvoke({"request": QUESTION}, cfg)
    await graph.ainvoke({"request": "Who issues the FLAF?"}, cfg)

    assert [name for name, _ in seen] == ["rag", "verifier", "synthesizer"] * 2
    assert sup.calls[1].history == [("user", QUESTION), ("assistant", "The sheet is issued by **PDO**.")]


async def test_without_a_supervisor_model_the_user_gets_a_clear_message(monkeypatch):
    from orchestrator_agent import llm

    monkeypatch.delenv("SUPERVISOR_LLM_MODEL", raising=False)
    llm.supervisor_model.cache_clear()
    graph, seen, _ = make_graph([], supervisor=LLMSupervisor())
    out = await graph.ainvoke({"request": QUESTION}, new_thread())
    llm.supervisor_model.cache_clear()
    assert "set SUPERVISOR_LLM_MODEL" in out["final"] and seen == []
