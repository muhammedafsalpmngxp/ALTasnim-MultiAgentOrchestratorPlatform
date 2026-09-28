"""
Verifier Agent — a bounded self-critique / reflection step for the chat pipeline.

WHY
The router + RAG/agent produce an answer, but nothing checks whether that answer actually (a)
addresses what the user asked, (b) honors the requested format/length, (c) is grounded in the
retrieved context (no hallucination), and (d) correctly declines when the topic isn't in the docs.
This agent is that check. When it judges an answer BAD, the caller regenerates once with the
verifier's feedback (bounded — max 1 retry), then returns the best result. On ANY failure the
verifier returns "good" so it can never block or break chat.

DESIGN
- One LLM call, temperature 0, small output (a compact JSON verdict).
- Prompt-engineered: Role / Goal / Backstory, chain-of-thought (reason silently), few-shot.
- Generic: no hardcoded user queries, keywords, or document topics.
- Toggle with env VERIFIER_ENABLED (default on). Bounded context to keep latency/token cost low.
"""
import json
import logging
import os
import re

_log = logging.getLogger("lt_rag_pipeline")

VERIFIER_ENABLED = os.environ.get("VERIFIER_ENABLED", "1") == "1"
_CTX_CHAR_LIMIT = 6000   # cap the grounding context handed to the verifier
_ANS_CHAR_LIMIT = 4000   # cap the answer handed to the verifier

_VERIFIER_PROMPT = (
    "ROLE\n"
    "You are the Verifier — a strict, fair quality-control reviewer for a document Q&A assistant. "
    "You do NOT answer the question yourself; you judge whether a drafted answer is good enough to "
    "send to the user.\n\n"
    "GOAL\n"
    "Decide if the DRAFT ANSWER should be sent as-is, or sent back for one revision. Judge only what "
    "matters to the user's experience.\n\n"
    "BACKSTORY\n"
    "The user asked a question about their uploaded documents. A retrieval system pulled CONTEXT "
    "excerpts, and an answer model wrote a DRAFT. You see the user's request, the context, and the "
    "draft. You must catch four failure types before the user sees them.\n\n"
    "CHECK THESE (reason silently, then output JSON):\n"
    "1. RELEVANCE — does the draft actually answer what the user asked (the real intent, including any "
    "follow-up meaning)? A draft that answers a different question, or returns a greeting/file-list when "
    "the user wanted content, is BAD.\n"
    "2. FORMAT/LENGTH — did the user ask for a specific form ('in 3 lines', 'two paragraphs', 'briefly', "
    "'as a table', 'in detail')? If so, the draft MUST match it. A 3-line request answered with 8 "
    "paragraphs is BAD. If no format was requested, don't penalize.\n"
    "3. GROUNDING — is every factual claim, number, name, and specification in the draft supported by the "
    "CONTEXT? If the draft invents facts not in the context, it is BAD (hallucination).\n"
    "4. HONEST DECLINE — if the CONTEXT does not contain the answer (topic not in the documents), the draft "
    "should say so, NOT fabricate. A fabricated answer to an out-of-scope question is BAD. A correct, "
    "graceful 'not covered in your documents' is GOOD.\n\n"
    "Be fair: minor wording/style differences are GOOD. Only flag BAD for a real problem in 1–4. "
    "Greetings and genuine 'not covered' replies are GOOD.\n\n"
    "OUTPUT — ONLY this single-line JSON, no markdown/code fences/commentary:\n"
    '{"verdict": "good"|"bad", "feedback": "<if bad: one concise instruction telling the answer model '
    'exactly how to fix it; else empty>"}\n\n'
    "FEW-SHOT (illustrative; reason generically):\n"
    'Request: "summarize the files in 3 lines" | Draft: an 8-paragraph summary → '
    '{"verdict":"bad","feedback":"Rewrite as exactly 3 lines summarizing the documents; keep only the '
    'most important points."}\n'
    'Request: "what does clause 5 say?" | Draft: correctly quotes clause 5 from context → '
    '{"verdict":"good","feedback":""}\n'
    'Request: "what is the capital of France?" | Context: construction docs only | Draft: "Paris." → '
    '{"verdict":"bad","feedback":"This topic is not in the uploaded documents; do not answer from outside '
    'knowledge — tell the user it is not covered and invite a question about their files."}\n'
    'Request: "tell me about the files" | Draft: a bullet list of file names only → '
    '{"verdict":"bad","feedback":"The user wants the CONTENT/subjects of the documents, not just file '
    'names; describe what the documents are about using the context."}'
)


def _condense_context(references: dict) -> str:
    """Build a compact grounding context from the retrieved chunks."""
    if not isinstance(references, dict):
        return ""
    chunks = references.get("chunks") or references.get("sources") or []
    parts = []
    for c in chunks:
        if not isinstance(c, dict):
            continue
        doc = c.get("document_name") or c.get("doc_name") or ""
        content = str(c.get("content") or "")
        if content:
            parts.append(f"[{doc}] {content}")
    ctx = "\n\n".join(parts)
    return ctx[:_CTX_CHAR_LIMIT]


async def verify_answer(user_request: str, answer: str, references: dict,
                        tenant_id: str, llm_id: str | None) -> dict:
    """Judge a drafted answer. Returns {"verdict": "good"|"bad", "feedback": str}.
    Returns "good" on any error or when disabled — it must never block chat."""
    if not VERIFIER_ENABLED:
        return {"verdict": "good", "feedback": ""}
    if not (answer or "").strip():
        return {"verdict": "good", "feedback": ""}
    try:
        from api.db.services.llm_service import LLMBundle
        from api.db.joint_services.tenant_model_service import get_model_config_from_provider_instance
        from common.constants import LLMType

        context = _condense_context(references)
        payload = (
            f"USER REQUEST:\n{user_request}\n\n"
            f"CONTEXT (retrieved excerpts the answer must be grounded in):\n{context or '(no excerpts retrieved)'}\n\n"
            f"DRAFT ANSWER:\n{(answer or '')[:_ANS_CHAR_LIMIT]}"
        )
        model_config = get_model_config_from_provider_instance(tenant_id, LLMType.CHAT, llm_id or None)
        mdl = LLMBundle(tenant_id, model_config)
        txt = await mdl.async_chat(_VERIFIER_PROMPT, [{"role": "user", "content": payload}], {"temperature": 0.0})
        txt = re.sub(r"<think>.*?</think>", "", (txt or ""), flags=re.DOTALL).strip()
        start, end = txt.find("{"), txt.rfind("}")
        if start == -1 or end == -1:
            return {"verdict": "good", "feedback": ""}
        parsed = json.loads(txt[start:end + 1])
        verdict = str(parsed.get("verdict", "good")).lower().strip()
        feedback = str(parsed.get("feedback", "") or "").strip()
        if verdict not in ("good", "bad"):
            verdict = "good"
        return {"verdict": verdict, "feedback": feedback}
    except Exception:
        _log.warning("[RAG] verifier failed — accepting draft answer as-is", exc_info=True)
        return {"verdict": "good", "feedback": ""}
