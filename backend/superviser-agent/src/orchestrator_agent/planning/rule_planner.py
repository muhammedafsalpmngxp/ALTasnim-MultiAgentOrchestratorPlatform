"""Rule-based planner: lets the whole platform run offline (no LLM key).

It understands the core patterns:
- "What is the retention money in the contract?"          -> rag -> synthesizer        (the user's documents)
- "What is the price of iPhone?"                           -> web_search -> synthesizer (the public web)
- "Check the price of iPhone then share the mail to x@y"   -> web_search -> synthesizer -> communication
- "Compare iPhone price in Oman and UAE and email it to x" -> web_search || web_search -> synthesizer -> communication
- "... and email it" (no address)                          -> clarify: who to send to?
- any other request, even keywords ("flaf and pegg")       -> rag (or web_search) -> synthesizer
- small talk ("hello", "what can you do")                  -> answered directly

The source is rag unless the question is about the web (prices, news, current events) or rag is not available.
When rag found nothing or its passages failed verification, the replan uses web_search. The verifier before the
synthesizer is added by policy.
Without a synthesizer (or rag) the plans are the ones above without those steps.

Replace with the LLM planner in production (set LLM_MODEL_STRONG).
"""

from __future__ import annotations

import re
from typing import Any

from utils import AgentCard, Plan, Step, SupervisorDecision

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SEND_RE = re.compile(r"\b(e-?mail|mail|send|share|notify|forward)\b", re.I)
# Where the "send" part of the request starts, e.g. " then share the mail to ..."
SEND_SPLIT_RE = re.compile(
    r"[\s,.;]*\b(?:and\s+then|then|and|also)?\s*\b(?:e-?mail|mail|send|share|notify|forward)\b", re.I
)
# small talk the supervisor answers itself; every other request is a question for the agents
SMALL_TALK_RE = re.compile(
    r"^\s*(hi|hello|hey|hai|good\s+(morning|afternoon|evening)|thanks?|thank\s+you|ok(ay)?|bye|who\s+are\s+you|"
    r"what\s+can\s+you\s+do|help)\b[\s!.?]*$",
    re.I,
)
# the user's own documents -> rag
DOC_RE = re.compile(r"\b(documents?|docs?|files?|pdfs?|contracts?|uploaded|policy|policies|clauses?|reports?|manuals?|"
                    r"rules|project)\b", re.I)
# the public web -> web_search
WEB_RE = re.compile(r"\b(price|prices|cost|latest|news|today|current|weather|stocks?|online|internet|web|compare)\b",
                    re.I)
COMPARE_RE = re.compile(r"\bcompare\s+(?P<subject>.+?)\s+in\s+(?P<a>.+?)\s+(?:and|vs\.?|versus)\s+(?P<b>.+)$", re.I)


def _clean(text: str) -> str:
    return EMAIL_RE.sub("", text).strip(" ,.;:-")


def _help(cards: dict[str, AgentCard]) -> str:
    """What the available agents can do, with an example question."""
    can = [text for agent, text in (("rag", "answer questions from your uploaded documents"),
                                    ("web_search", "search the web for current information (prices, news)"),
                                    ("communication", "email the results")) if agent in cards]
    if not can:
        return "No agent is available right now. Please try again in a moment."
    example = "Who issues the pegging sheet?" if "rag" in cards else "What is the price of iPhone?"
    return f"Hi! I can {', '.join(can[:-1]) + ' and ' + can[-1] if len(can) > 1 else can[0]}. Try: '{example}'"


def _pick_source(question: str, cards: dict[str, AgentCard], feedback: list[str]) -> str | None:
    """Where the facts come from: the user's documents (rag) or the public web (web_search)."""
    rag = "rag" in cards and not any("(rag)" in f for f in feedback)  # rag failed / failed verification: the web
    web = "web_search" in cards
    if rag and (DOC_RE.search(question) or not WEB_RE.search(question) or not web):
        return "rag"
    return "web_search" if web else None


class RulePlanner:
    def decide(
        self,
        request: str,
        clarifications: list[str],
        cards: dict[str, AgentCard],
        done: dict[str, Any],
        feedback: list[str],
    ) -> SupervisorDecision:
        full_text = " ".join([request, *clarifications])
        emails = list(dict.fromkeys(EMAIL_RE.findall(full_text)))
        wants_send = bool(SEND_RE.search(request)) and "communication" in cards

        match = SEND_SPLIT_RE.search(request) if wants_send else None
        info_part = _clean(request[: match.start()] if match else request)  # "mail it to x" alone: no question
        source = _pick_source(info_part, cards, feedback)
        wants_info = source is not None and bool(info_part) and not SMALL_TALK_RE.match(info_part)

        steps: list[Step] = []
        if wants_info and source == "rag":
            steps.append(Step(id="s1", agent="rag", objective=f"Find passages in the documents about: {info_part}",
                              params={"question": info_part}))
        elif wants_info:
            if cmp := COMPARE_RE.search(info_part):
                subject = cmp["subject"].strip()
                for i, region in enumerate((cmp["a"].strip(), cmp["b"].strip()), start=1):
                    steps.append(Step(id=f"s{i}", agent="web_search", objective=f"Find {subject} in {region}",
                                      params={"query": subject, "region": region}))
            else:
                steps.append(Step(id="s1", agent="web_search", objective=info_part[:1].upper() + info_part[1:]))

        if steps and "synthesizer" in cards:  # one final answer from the found facts
            sources = [s.id for s in steps]
            steps.append(Step(id=f"s{len(steps) + 1}", agent="synthesizer",
                              objective=f"Write the final answer to: {info_part}",
                              params={"question": info_part}, depends_on=sources))

        if wants_send:
            if not emails:
                return SupervisorDecision(action="clarify", reasoning="Send requested but no recipient given.",
                                          question="Who should I send it to? Please give the email address.")
            subject = (info_part or "Requested information")[:1].upper() + (info_part or "Requested information")[1:]
            steps.append(Step(
                id=f"s{len(steps) + 1}",
                agent="communication",
                objective=f"Email the results to {', '.join(emails)}",
                params={"channel": "email", "to": emails, "subject": subject[:120]},
                # the final answer if there is one, else everything found
                depends_on=[s.id for s in steps if s.agent == "synthesizer"] or [s.id for s in steps],
            ))

        if not steps:
            return SupervisorDecision(action="answer", reasoning="Small talk: no agent needed.", answer=_help(cards))

        agents = " -> ".join(dict.fromkeys(s.agent for s in steps))
        if source == "web_search" and "rag" in cards and any("(rag)" in f for f in feedback):
            agents += " (the documents did not answer it)"
        return SupervisorDecision(
            action="plan",
            reasoning=f"Rule-based plan: {agents}.",
            plan=Plan(goal=request, reasoning=f"Rule-based plan: {agents}.", steps=steps),
        )
