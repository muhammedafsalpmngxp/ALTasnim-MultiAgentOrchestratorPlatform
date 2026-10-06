"""The supervisor controls the whole flow through the real orchestrator graph: its decisions (here scripted, in
production its LLM) become the plan, progress runs the plan, and the supervisor reviews on events. The platform adds
its check (the verifier) after the final answer; a failed check sends the supervisor back to redo only what it names.
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
PASS = {"status": "ok", "passed": True, "summary": "Verified: PDO issues the pegging sheet", "rejected_steps": [],
        "fix": "none"}


def plan(*items: dict) -> SupervisorDecision:
    steps = [Step(**s) for s in items]
    return SupervisorDecision(action="plan", understanding="who issues the sheet", reasoning="scripted",
                              plan=Plan(goal=QUESTION, success_criteria=["the issuer"], steps=steps))


def answer_plan(source: str, ids=("s1", "s2"), objective="Answer") -> SupervisorDecision:
    """source -> synthesizer, as the LLM is asked to plan a question (the platform adds the check)."""
    a, f = ids
    params = {"question": QUESTION} if source == "rag" else {"query": QUESTION}
    return plan({"id": a, "agent": source, "objective": f"Find who issues the pegging sheet ({source})",
                 "params": params},
                {"id": f, "agent": "synthesizer", "objective": objective, "params": {"question": QUESTION},
                 "depends_on": [a]})


def docs_then_web(ctx):
    """The documents first; when they fail or are rejected, the web (what the LLM decides from the cards)."""
    if ctx.mode == "plan":
        return answer_plan("rag")
    return answer_plan("web_search", ids=("s3", "s4"))


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


def matches_the_question(task):
    """The check: an answer about something else than the issuer does not match the question (rewrite it)."""
    answer = task["inputs"][task["params"]["answer_step"]]["answer"]
    if "PDO" not in answer:
        return {"status": "failed", "passed": False, "summary": "Verification failed: off topic: not about the issuer",
                "missing": [], "rejected_steps": [task["params"]["answer_step"]], "fix": "rewrite_answer"}
    return PASS


def make_graph(rag_chunks, script=docs_then_web, check=matches_the_question, extra=None, supervisor=None,
               policies=None):
    seen = []

    def rag(task):
        if not rag_chunks:
            return {"status": "failed", "summary": "No passage in the documents matches the question", "chunks": []}
        return {"status": "ok", "question": task["params"]["question"], "chunks": rag_chunks}  # like Rag: no summary

    def synthesizer(task):  # answers from its inputs: unrelated passages give an answer about something else
        if "Unrelated" in str(task["inputs"]):
            return {"status": "ok", "summary": "x", "answer": "Visitors must wear a hard hat."}
        return {"status": "ok", "summary": "PDO", "answer": "The sheet is issued by **PDO**."}

    def entry(name, graph, card):
        return AgentEntry(name, LocalAgentClient(graph), card, fetched_at=float("inf"))

    entries = {
        "rag": entry("rag", recording_agent("rag", rag, seen), RAG),
        "web_search": entry("web_search", build_stub_agent("web_search", {"status": "ok", "summary": "web: PDO"}),
                            SEARCH),
        "verifier": entry("verifier", recording_agent("verifier", check, seen), VERIFIER),
        "synthesizer": entry("synthesizer", recording_agent("synthesizer", synthesizer, seen), SYNTH),
    }
    for name, (card, reply) in (extra or {}).items():
        entries[name] = entry(name, recording_agent(name, reply, seen), card)
    supervisor = supervisor or ScriptedSupervisor(script)
    deps = Deps(registry=AgentRegistry(entries), supervisor=supervisor, policies=policies or Policies())
    return build_graph(deps=deps, checkpointer=InMemorySaver()), seen, supervisor


def new_thread():
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


async def test_the_platform_checks_the_answer_after_one_supervisor_call():
    graph, seen, sup = make_graph([{"content": "PDO issues the pegging sheet", "document_name": "rules.pdf"}])
    assert {"rag", "web_search", "verifier", "synthesizer"} <= set(graph.get_graph().nodes)

    out = await graph.ainvoke({"request": QUESTION}, new_thread())

    assert out["final"] == "The sheet is issued by **PDO**."
    assert [name for name, _ in seen] == ["rag", "synthesizer", "verifier"]
    assert len(sup.calls) == 1 and sup.calls[0].mode == "plan"  # passed: no review
    assert set(sup.calls[0].cards) == {"rag", "web_search", "synthesizer"}  # the LLM never plans the verifier
    synth = seen[1][1]
    assert synth["params"]["question"] == QUESTION and set(synth["inputs"]) == {"s1"}
    check = seen[2][1]
    assert set(check["inputs"]) == {"s2"}  # the answer only: no sources
    assert check["params"] == {"request": QUESTION, "answer_step": "s2"}
    check_step = next(s for s in out["plan"]["steps"] if s["agent"] == "verifier")
    assert (check_step["id"], check_step["added_by"]) == ("check_s2", "policy")


async def test_nothing_in_the_documents_the_supervisor_reviews_and_uses_the_web():
    graph, seen, sup = make_graph([])
    out = await graph.ainvoke({"request": QUESTION}, new_thread())

    assert out["final"] == "The sheet is issued by **PDO**."
    assert [name for name, _ in seen] == ["rag", "synthesizer", "verifier"]  # rag failed: nothing else ran
    review = sup.calls[1]
    assert (review.mode, review.review_reason) == ("review", "failed")
    assert review.results["s1"]["status"] == "failed"
    assert any("(rag) failed" in f for f in review.feedback)
    assert out["plan"]["version"] == 2 and out["replans"] == 1
    assert set(out["results"]) == {"s3", "s4", "check_s4"}  # the failed plan's results are gone
    assert seen[1][1]["inputs"]["s3"]["summary"] == "web: PDO"  # the new answer is written from the web


async def test_an_answer_that_does_not_match_is_redone_and_checked_again():
    graph, seen, sup = make_graph([{"content": "Unrelated clause", "document_name": "rules.pdf"}])
    out = await graph.ainvoke({"request": QUESTION}, new_thread())

    assert out["final"] == "The sheet is issued by **PDO**."
    # rag -> synthesizer -> check fails -> (review) web_search -> synthesizer -> check passes
    assert [name for name, _ in seen] == ["rag", "synthesizer", "verifier", "synthesizer", "verifier"]
    review = sup.calls[1]
    assert review.results["s1"]["status"] == "ok"  # the check blames only the answer
    assert review.results["s2"]["status"] == "failed" and "failed verification" in review.results["s2"]["error"]
    assert any("how to fix (check_s2): the answer does not match the question" in f for f in review.feedback)


async def test_a_rewrite_reruns_only_the_answer_and_keeps_the_found_facts():
    def check(task):  # the first answer leaves out the department; the rewritten one has it
        if "department" in task["inputs"][task["params"]["answer_step"]].get("answer", ""):
            return PASS
        return {"status": "failed", "passed": False, "summary": "Verification failed: missing: the department",
                "missing": ["the department"], "rejected_steps": [task["params"]["answer_step"]],
                "fix": "rewrite_answer"}

    def script(ctx):
        if ctx.mode == "plan":
            return answer_plan("rag")
        assert any("how to fix (check_s2): the answer does not match the question" in f for f in ctx.feedback)
        assert ctx.results["s1"]["status"] == "ok" and ctx.results["s2"]["status"] == "failed"
        return answer_plan("rag", ids=("s1", "s3"), objective="Answer, and name the department")

    graph, seen, sup = make_graph([{"content": "PDO's survey department issues it", "document_name": "rules.pdf"}],
                                  script=script, check=check,
                                  extra={"synthesizer": (SYNTH, lambda task: {
                                      "status": "ok", "summary": "x",
                                      "answer": "PDO's survey department." if "department" in task["objective"]
                                      else "PDO."})})
    out = await graph.ainvoke({"request": QUESTION}, new_thread())

    assert [name for name, _ in seen] == ["rag", "synthesizer", "verifier", "synthesizer", "verifier"]  # rag once
    assert out["final"] == "PDO's survey department."
    assert out["results"]["check_s3"]["output"]["passed"] is True and out["replans"] == 1


async def test_a_check_that_could_not_run_blames_no_step():
    def check(task):
        return {"status": "failed", "passed": False, "summary": "Verification failed: verification could not run",
                "rejected_steps": [], "fix": "none"}

    def script(ctx):
        if ctx.mode == "plan":
            return answer_plan("rag")
        assert ctx.results["s1"]["status"] == "ok" and ctx.results["s2"]["status"] == "ok"  # nothing rejected
        assert any("the check itself could not run" in f for f in ctx.feedback)
        return SupervisorDecision(action="finish")

    graph, seen, sup = make_graph([{"content": "PDO issues it", "document_name": "rules.pdf"}], script=script,
                                  check=check)
    out = await graph.ainvoke({"request": QUESTION}, new_thread())
    assert out["final"] == "The sheet is issued by **PDO**."  # the supervisor finished with the answer


async def test_failing_checks_stop_at_the_replan_limit_with_an_honest_reply():
    def check(task):
        return {"status": "failed", "passed": False, "summary": "Verification failed: missing: the issuer",
                "rejected_steps": [task["params"]["answer_step"]], "fix": "rewrite_answer"}

    def script(ctx):
        if ctx.mode == "review" and ctx.replans_left == 0:
            return SupervisorDecision(action="answer", answer="I could not confirm who issues the sheet.")
        n = len(ctx.feedback)
        return answer_plan("rag", ids=("s1", f"a{n}"))

    graph, seen, sup = make_graph([{"content": "PDO issues it", "document_name": "rules.pdf"}], script=script,
                                  check=check)
    out = await graph.ainvoke({"request": QUESTION}, new_thread())
    assert out["final"] == "I could not confirm who issues the sheet."
    assert out["replans"] == Policies().max_replans
    assert [name for name, _ in seen].count("verifier") == 1 + Policies().max_replans
    assert [name for name, _ in seen].count("rag") == 1  # the facts were kept every time


async def test_with_verify_final_off_there_is_no_check():
    graph, seen, sup = make_graph([{"content": "PDO issues it", "document_name": "rules.pdf"}],
                                  policies=Policies(verify_final=False))
    out = await graph.ainvoke({"request": QUESTION}, new_thread())
    assert [name for name, _ in seen] == ["rag", "synthesizer"]
    assert out["final"] == "The sheet is issued by **PDO**."


async def test_without_a_final_answer_agent_the_supervisor_reviews_and_writes_the_answer():
    def script(ctx):
        if ctx.mode == "plan":
            return plan({"id": "s1", "agent": "rag", "objective": "find", "params": {"question": QUESTION}})
        assert ctx.review_reason == "complete" and ctx.results["s1"]["status"] == "ok"
        return SupervisorDecision(action="finish", answer="PDO issues it (rules.pdf).")

    graph, seen, sup = make_graph([{"content": "PDO issues the pegging sheet", "document_name": "rules.pdf"}],
                                  script=script)
    out = await graph.ainvoke({"request": QUESTION}, new_thread())
    assert out["final"] == "PDO issues it (rules.pdf)." and len(sup.calls) == 2
    assert [name for name, _ in seen] == ["rag"]


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
    assert seen[-1][1]["params"]["request"] == f"{QUESTION}\nrules.pdf"  # the check knows the user's answer too


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
    assert [name for name, _ in seen] == ["rag", "translator", "synthesizer", "verifier"]
    assert seen[1][1]["inputs"]["s1"]["chunks"][0]["content"] == "PDO issues it"
    assert set(seen[3][1]["inputs"]) == {"s3"}  # the check sees the answer only
    assert out["final"] == "The sheet is issued by **PDO**."


async def test_each_question_in_a_chat_runs_the_agents_again_and_sees_the_history():
    """A second question on the same thread must not reuse the first question's agent threads (old answers)."""
    graph, seen, sup = make_graph([{"content": "PDO issues the pegging sheet", "document_name": "rules.pdf"}])
    cfg = new_thread()

    await graph.ainvoke({"request": QUESTION}, cfg)
    await graph.ainvoke({"request": "Who issues the FLAF?"}, cfg)

    assert [name for name, _ in seen] == ["rag", "synthesizer", "verifier"] * 2
    assert sup.calls[1].history == [("user", QUESTION), ("assistant", "The sheet is issued by **PDO**.")]


async def test_without_a_supervisor_model_the_user_gets_a_clear_message(monkeypatch):
    from orchestrator_agent import llm

    monkeypatch.delenv("SUPERVISOR_LLM_MODEL", raising=False)
    llm.supervisor_model.cache_clear()
    graph, seen, _ = make_graph([], supervisor=LLMSupervisor())
    out = await graph.ainvoke({"request": QUESTION}, new_thread())
    llm.supervisor_model.cache_clear()
    assert "set SUPERVISOR_LLM_MODEL" in out["final"] and seen == []
