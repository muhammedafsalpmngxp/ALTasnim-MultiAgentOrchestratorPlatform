"""Rule-based planner: lets the whole platform run offline (no LLM key).

It understands the core patterns:
- "What is the price of iPhone?"                           -> web_search
- "Check the price of iPhone then share the mail to x@y"   -> web_search -> communication
- "Compare iPhone price in Oman and UAE and email it to x" -> web_search || web_search -> communication
- "... and email it" (no address)                          -> clarify: who to send to?

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
INFO_RE = re.compile(
    r"\b(price|prices|cost|find|search|check|look\s*up|latest|news|what|who|when|where|how\s+much|compare|current)\b",
    re.I,
)
COMPARE_RE = re.compile(r"\bcompare\s+(?P<subject>.+?)\s+in\s+(?P<a>.+?)\s+(?:and|vs\.?|versus)\s+(?P<b>.+)$", re.I)


def _clean(text: str) -> str:
    return EMAIL_RE.sub("", text).strip(" ,.;:-")


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
        info_part = _clean(request[: match.start()] if match and match.start() > 0 else request)
        wants_info = bool(INFO_RE.search(info_part)) and "web_search" in cards

        steps: list[Step] = []
        if wants_info:
            if cmp := COMPARE_RE.search(info_part):
                subject = cmp["subject"].strip()
                for i, region in enumerate((cmp["a"].strip(), cmp["b"].strip()), start=1):
                    steps.append(Step(id=f"s{i}", agent="web_search", objective=f"Find {subject} in {region}",
                                      params={"query": subject, "region": region}))
            else:
                steps.append(Step(id="s1", agent="web_search", objective=info_part[:1].upper() + info_part[1:]))

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
                depends_on=[s.id for s in steps],
            ))

        if not steps:
            return SupervisorDecision(
                action="answer",
                reasoning="No agent matches this request.",
                answer=("I can search the web for current information (e.g. prices, news) and email results. "
                        "Try: 'Check the price of iPhone then share the mail to someone@example.com'."),
            )

        agents = " -> ".join(dict.fromkeys(s.agent for s in steps))
        return SupervisorDecision(
            action="plan",
            reasoning=f"Rule-based plan: {agents}.",
            plan=Plan(goal=request, reasoning=f"Rule-based plan: {agents}.", steps=steps),
        )
