"""
Chat sessions + SSE streaming using RAGFlow's pipeline.
A session links to one or more projects (knowledge bases) and searches across all of them.
"""
import asyncio
import json
import logging
import re
import uuid
from typing import AsyncGenerator, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.core.config import settings
from api.core.deps import AuthUser
from api.routes.projects import _ts

router = APIRouter()

# Structured, single-line RAG pipeline logging — separate from RAGFlow's own verbose
# [HISTORY]/[HISTORY STREAMLY] dumps, so the router's decision and retrieval/rerank results are
# easy to find and grep for (search logs for "[RAG]") instead of parsing the full prompt dumps.
_rag_log = logging.getLogger("lt_rag_pipeline")


class CreateSessionRequest(BaseModel):
    project_ids: List[str]              # one or more project IDs to search across
    title: Optional[str] = "New Chat"
    top_n: Optional[int] = 10
    similarity_threshold: Optional[float] = 0.2


class RenameSessionRequest(BaseModel):
    title: str


class ChatRequest(BaseModel):
    message: str
    stream: bool = True


def _kb_ids_from_dialog(dialog) -> List[str]:
    """Return all KB/project IDs from a dialog's kb_ids field."""
    kb_ids = getattr(dialog, "kb_ids", None) or []
    if isinstance(kb_ids, str):
        try:
            kb_ids = json.loads(kb_ids)
        except Exception:
            kb_ids = [kb_ids] if kb_ids else []
    return [str(k) for k in kb_ids if k]


def _fmt_session(s, project_ids: List[str] = None) -> dict:
    return {
        "id": str(s.id),
        "title": getattr(s, "name", ""),
        "project_ids": project_ids or [],
        "message_count": len(getattr(s, "message", []) or []),
        "created_at": _ts(getattr(s, "create_time", "")),
        "updated_at": _ts(getattr(s, "update_time", "")),
    }


def _get_conv(session_id: str, tenant_id: str):
    from api.db.services.conversation_service import ConversationService
    from api.db.services.dialog_service import DialogService
    ok, conv = ConversationService.get_by_id(session_id)
    if not ok or not conv:
        raise HTTPException(status_code=404, detail="Session not found")
    ok2, dialog = DialogService.get_by_id(str(conv.dialog_id))
    if not ok2 or not dialog or str(getattr(dialog, "tenant_id", "")) != tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return conv


def _get_dialog(dialog_id: str, tenant_id: str):
    from api.db.services.dialog_service import DialogService
    ok, dialog = DialogService.get_by_id(dialog_id)
    if not ok or not dialog:
        raise HTTPException(status_code=404, detail="Dialog not found")
    if str(getattr(dialog, "tenant_id", "")) != tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return dialog


_INTENT_ROUTER_PROMPT = (
    "ROLE\n"
    "You are the Router — the first-pass reasoning step of a document Q&A (RAG) assistant, running "
    "BEFORE retrieval. You are precise and context-aware, like the planner inside a top-tier AI "
    "assistant.\n\n"
    "GOAL\n"
    "Understand what the user REALLY wants (using the conversation so far), then classify the request "
    "and produce a clean, self-contained search query for the pipeline.\n\n"
    "BACKSTORY\n"
    "The user is chatting about their uploaded project documents. Messages arrive as a conversation: "
    "earlier turns are CONTEXT; the LAST user message is the one you must classify. Short follow-ups "
    "('in 3 lines', 'shorter', 'as a paragraph', 'explain that', 'and the second one?') refer to the "
    "PREVIOUS turn — you must resolve them using the conversation, not treat them as new or as chit-chat.\n\n"
    "OUTPUT\n"
    "Respond with ONLY a single-line JSON object — no markdown, no code fences, no commentary:\n"
    '{"is_greeting": bool, "reply": "<string, only if is_greeting else empty>", '
    '"retrieval_query": "<self-contained query, empty if is_greeting or wants_file_list>", '
    '"needs_broad_context": bool, "wants_file_list": bool, "needs_agent": bool}\n\n"'
    "REASON THROUGH THESE STEPS (silently), then emit the JSON:\n\n"
    "1) is_greeting — true for pure social talk OR questions about the ASSISTANT ITSELF (not the "
    "documents): greetings ('hi', 'hello', 'good morning', 'how are you', 'thanks', 'bye') AND "
    "identity/capability questions about you ('who are you', 'what is your name', 'what can you do', "
    "'how do you work'). These are answered from your persona, NOT by searching documents. It is NOT a "
    "greeting if the message asks for or refines any DOCUMENT information. A terse instruction like "
    "'in 3 lines', 'make it shorter', 'in a paragraph', 'more detail' is a REFINEMENT of the previous "
    "answer, NOT a greeting. When is_greeting is true, write a short warm 'reply': for greetings, "
    "introduce yourself as the L&T Files Assistant and invite a question about their documents; for "
    "identity/capability questions, answer directly (you are the L&T Files Assistant, an AI assistant "
    "that helps them find and understand information in their uploaded project documents). Do NOT reveal "
    "internal model or technical implementation details. Leave all other fields empty/false.\n\n"
    "2) retrieval_query — a SELF-CONTAINED restatement of what the user wants right now, suitable both "
    "for searching the documents AND for the answer model. It must:\n"
    "   - Resolve follow-ups/pronouns using the conversation (e.g. after a files summary, 'in 3 lines' "
    "     → 'Summarize the uploaded documents in 3 lines'; 'and the second one?' → the resolved full "
    "     question).\n"
    "   - PRESERVE any format/length/style the user asked for — keep phrases like 'in 3 lines', 'in two "
    "     paragraphs', 'briefly', 'in detail', 'as a table' in the query so the answer honors them.\n"
    "   - NEVER change the user's actual meaning or resolve an ambiguous word to a sense they didn't "
    "     intend; when unsure, keep their wording. If nothing needs resolving, use the message as-is.\n\n"
    "3) needs_broad_context — true when a correct answer needs MANY/ALL parts of the documents rather "
    "than one passage: summaries/overviews ('what is this about', 'summarize the files'), and "
    "comparison/ranking/counting/exhaustive-listing over many records. False for a normal question "
    "answerable from one or a few passages.\n\n"
    "4) wants_file_list — true ONLY when the user asks about the IDENTITY of the uploaded files "
    "themselves: which files exist, their NAMES, or HOW MANY files there are. It is FALSE when they ask "
    "about the CONTENT of the files — 'summarize the files', 'tell me about the files', 'what do the "
    "documents cover' are CONTENT requests (needs_broad_context), NOT file-list requests.\n\n"
    "5) needs_agent — true ONLY when answering needs MULTIPLE dependent steps or real computation that a "
    "single retrieval pass cannot do. Ask yourself what a person would DO: just read a passage (false), "
    "or gather specific values and then calculate/compare/verify (true)? True for: superlatives over "
    "records (highest/lowest/top-N — must gather all rows then compare); aggregates (sum/avg/count/"
    "difference); comparing two named values and computing their difference/ratio; cross-document "
    "agreement checks (do two documents match/contradict); arithmetic on extracted values then using the "
    "result. False for summaries, listings, and simple lookups (even broad ones). When uncertain, false.\n\n"
    "FEW-SHOT (illustrative only — reason generically, do not memorize these):\n"
    'History: [assistant summarized the files] | User: "in 3 lines" → '
    '{"is_greeting":false,"reply":"","retrieval_query":"Summarize the uploaded documents in 3 lines",'
    '"needs_broad_context":true,"wants_file_list":false,"needs_agent":false}\n'
    'User: "tell me about the files in two paragraphs" → '
    '{"is_greeting":false,"reply":"","retrieval_query":"Describe the uploaded documents in two paragraphs",'
    '"needs_broad_context":true,"wants_file_list":false,"needs_agent":false}\n'
    'User: "which files are uploaded?" → '
    '{"is_greeting":false,"reply":"","retrieval_query":"","needs_broad_context":false,'
    '"wants_file_list":true,"needs_agent":false}\n'
    'User: "hello" → {"is_greeting":true,"reply":"Hello! I\'m the L&T Files Assistant — ask me anything '
    'about your uploaded project documents.","retrieval_query":"","needs_broad_context":false,'
    '"wants_file_list":false,"needs_agent":false}\n'
    'User: "what is your name / who are you?" → {"is_greeting":true,"reply":"I\'m the L&T Files Assistant, '
    'an AI assistant that helps you find and understand information in your uploaded project documents. '
    'What would you like to know?","retrieval_query":"","needs_broad_context":false,'
    '"wants_file_list":false,"needs_agent":false}\n'
    'User: "which item has the highest value, and what is it?" → '
    '{"is_greeting":false,"reply":"","retrieval_query":"which item has the highest value and what is it",'
    '"needs_broad_context":true,"wants_file_list":false,"needs_agent":true}\n'
    'History: [assistant explained clause A] | User: "does the other document agree with that?" → '
    '{"is_greeting":false,"reply":"","retrieval_query":"Do the documents agree on <the point from clause A>?",'
    '"needs_broad_context":true,"wants_file_list":false,"needs_agent":true}'
)


async def _classify_intent(message: str, tenant_id: str, llm_id: str | None, history: list | None = None) -> dict:
    """First-pass reasoning step, run before retrieval. Decides whether to short-circuit with a
    direct reply (greetings, or file-identity questions answered from real KB metadata instead of
    content search), and otherwise prepares the query that goes into the unchanged RAG pipeline:
    a self-contained, context-resolved rewrite (follow-ups like "in 3 lines" resolved against the
    conversation, and format/length constraints preserved), plus flags for broad coverage and for
    the multi-step Analysis Agent. `history` is the recent conversation so the router can resolve
    follow-ups; it is passed as prior chat turns before the current message."""
    fallback = {
        "is_greeting": False, "reply": "", "retrieval_query": message,
        "needs_broad_context": False, "wants_file_list": False, "needs_agent": False,
    }
    try:
        from api.db.services.llm_service import LLMBundle
        from api.db.joint_services.tenant_model_service import get_model_config_from_provider_instance
        from common.constants import LLMType

        model_config = get_model_config_from_provider_instance(tenant_id, LLMType.CHAT, llm_id or None)
        router_mdl = LLMBundle(tenant_id, model_config)
        # Recent turns as context (bounded) + the current message last, so the router can resolve
        # follow-ups ("in 3 lines", "the second one") against what was just discussed.
        convo = []
        for turn in (history or [])[-6:]:
            role = turn.get("role") if isinstance(turn, dict) else None
            content = str((turn.get("content") if isinstance(turn, dict) else "") or "")
            if role in ("user", "assistant") and content:
                convo.append({"role": role, "content": content[:1500]})
        convo.append({"role": "user", "content": message})
        txt = await router_mdl.async_chat(_INTENT_ROUTER_PROMPT, convo, {"temperature": 0.0})
        # Strip <think>...</think> — reasoning models (e.g. Qwen3 via Ollama) emit a thinking block
        # that can contain braces and would break the find("{")..rfind("}") JSON extraction below.
        txt = re.sub(r"<think>.*?</think>", "", (txt or ""), flags=re.DOTALL).strip()
        start, end = txt.find("{"), txt.rfind("}")
        if start == -1 or end == -1:
            return fallback
        parsed = json.loads(txt[start:end + 1])
        is_greeting = bool(parsed.get("is_greeting"))
        retrieval_query = str(parsed.get("retrieval_query") or "").strip() or message
        needs_broad_context = bool(parsed.get("needs_broad_context"))
        wants_file_list = bool(parsed.get("wants_file_list"))
        return {
            "is_greeting": is_greeting,
            "reply": str(parsed.get("reply") or ""),
            "retrieval_query": retrieval_query,
            "needs_broad_context": needs_broad_context,
            "wants_file_list": wants_file_list,
            "needs_agent": bool(parsed.get("needs_agent")),
        }
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Intent routing failed, defaulting to plain document_query", exc_info=True)
        return fallback


_SYSTEM_PROMPT = (
    "You are the L&T Files Assistant, an AI assistant for L&T construction and engineering project "
    "documents. You answer strictly and only from the retrieved document context provided to you.\n\n"
    "OUTPUT RULES (follow exactly):\n"
    "1. Output ONLY the final answer. NEVER include your reasoning, planning, chain-of-thought, or any "
    "<think>...</think> content. No preamble like 'Based on the context' — just answer.\n"
    "2. Be concise and direct: answer exactly what is asked, nothing more. No unrelated information, no "
    "filler, no repetition. Prefer short sentences or tight bullet points for lists/steps.\n"
    "3. Ground every fact, number, and name in the retrieved context. Do NOT use outside or training "
    "knowledge. Do NOT guess, assume, or invent anything — if it is not in the context, do not say it "
    "(no hallucination).\n"
    "4. Use the document's own terms and figures. Do not paraphrase numbers or technical terms loosely.\n"
    "5. For summary/overview questions, summarise the actual topics, scope, and key points present in the "
    "retrieved context — do not add anything not found there.\n"
    "6. If the retrieved context does not contain the answer, say plainly that the uploaded documents do "
    "not cover it. Never fabricate to fill the gap.\n"
    "7. If the question is unrelated to the project documents (e.g. weather, sports, general knowledge), "
    "reply exactly: 'I can only answer questions about the documents in this project.'\n"
    "8. Be professional and neutral."
)


class _ThinkFilter:
    """Streaming filter that hides a leading <think>...</think> reasoning block from token deltas
    before they reach the UI.

    Reasoning models (e.g. Qwen3 via Ollama) prepend their internal chain-of-thought wrapped in
    <think>...</think>; end users must see ONLY the final answer. The tags can arrive split across
    streamed deltas, so this buffers the minimum needed to decide, then passes everything after the
    closing tag straight through. If the stream never starts with <think>, it flushes immediately —
    a no-op for models (or endpoints) that already return clean content."""
    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self):
        self._buf = ""
        self._state = "start"  # start -> thinking | passthrough

    def feed(self, delta: str) -> str:
        if self._state == "passthrough":
            return delta
        self._buf += delta
        if self._state == "start":
            head = self._buf.lstrip()
            if not head:
                return ""  # only whitespace so far — wait
            if head.startswith(self._OPEN):
                self._state = "thinking"  # fall through to thinking handling
            elif self._OPEN.startswith(head):
                return ""  # head is a partial prefix of "<think>" — wait for more
            else:
                self._state = "passthrough"  # definitely not thinking — flush
                out, self._buf = self._buf, ""
                return out
        # state == thinking: suppress until the closing tag, then emit the remainder
        idx = self._buf.find(self._CLOSE)
        if idx == -1:
            return ""
        after = self._buf[idx + len(self._CLOSE):]
        self._buf = ""
        self._state = "passthrough"
        return after.lstrip()

    def flush(self) -> str:
        # Stream ended while still undecided (partial buffer that never became <think>): emit it.
        if self._state == "start":
            out, self._buf = self._buf, ""
            self._state = "passthrough"
            return out
        return ""


def _strip_think(text: str) -> str:
    """Remove any <think>...</think> blocks from a complete (non-streamed) string."""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


@router.post("/chat/sessions")
async def create_session(req: CreateSessionRequest, user: AuthUser):
    try:
        from api.db.services.dialog_service import DialogService
        from api.db.services.conversation_service import ConversationService
        from api.db.services.knowledgebase_service import KnowledgebaseService

        if not req.project_ids:
            raise HTTPException(status_code=400, detail="At least one project_id is required")

        # Validate all project IDs belong to this user's tenant
        validated_ids = []
        for pid in req.project_ids:
            ok, kb = KnowledgebaseService.get_by_id(pid)
            if not ok or not kb or str(kb.tenant_id) != user.tenant_id:
                raise HTTPException(status_code=404, detail=f"Project not found: {pid}")
            validated_ids.append(pid)

        # Resolve rerank model
        _rerank_id = settings.active_rerank_ragflow_id
        try:
            from api.db.services.user_service import TenantService
            _, tenant = TenantService.get_by_id(user.tenant_id)
            tenant_rerank = str(getattr(tenant, "rerank_id", "") or "")
            if tenant_rerank:
                _rerank_id = tenant_rerank
        except Exception:
            pass

        # Always create a fresh Dialog for each session (supports arbitrary project_ids combos)
        dialog_id = uuid.uuid4().hex
        DialogService.save(**{
            "id": dialog_id,
            "tenant_id": user.tenant_id,
            "kb_ids": validated_ids,
            "name": f"Session {req.title}",
            "description": "",
            "icon": "",
            "language": "English",
            "llm_id": "",
            "rerank_id": _rerank_id,
            "llm_setting": {},
            "prompt_config": {
                "system": _SYSTEM_PROMPT,
                "prologue": "Hello! I'm the L&T Files Assistant. How can I help you?",
                "quote": True,
                "keyword": False,
            },
            "similarity_threshold": req.similarity_threshold,
            "vector_similarity_weight": 0.5,
            "top_n": req.top_n,
            "status": "1",
        })
        ok, dialog = DialogService.get_by_id(dialog_id)

        session_id = uuid.uuid4().hex
        ConversationService.save(**{
            "id": session_id,
            "dialog_id": str(dialog.id),
            "name": req.title,
            "message": [{"role": "assistant", "content": "Hello! I'm the L&T Files Assistant. How can I help you?"}],
        })
        ok, conv = ConversationService.get_by_id(session_id)
        return _fmt_session(conv, project_ids=validated_ids)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat/sessions")
async def list_sessions(user: AuthUser):
    try:
        from api.db.services.conversation_service import ConversationService
        from api.db.services.dialog_service import DialogService

        dialogs = DialogService.query(tenant_id=user.tenant_id, status="1")
        sessions = []
        for d in dialogs:
            project_ids = _kb_ids_from_dialog(d)
            for s in ConversationService.query(dialog_id=str(d.id)):
                sessions.append(_fmt_session(s, project_ids=project_ids))
        return sessions
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat/sessions/{session_id}")
async def get_session(session_id: str, user: AuthUser):
    try:
        conv = _get_conv(session_id, user.tenant_id)
        dialog = _get_dialog(str(conv.dialog_id), user.tenant_id)
        project_ids = _kb_ids_from_dialog(dialog)
        return {**_fmt_session(conv, project_ids=project_ids), "messages": getattr(conv, "message", []) or []}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/chat/sessions/{session_id}")
async def rename_session(session_id: str, req: RenameSessionRequest, user: AuthUser):
    try:
        from api.db.services.conversation_service import ConversationService
        from api.db.services.dialog_service import DialogService
        conv = _get_conv(session_id, user.tenant_id)
        title = req.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Title cannot be empty")
        ConversationService.update_by_id(session_id, {"name": title})
        ok, dialog = DialogService.get_by_id(str(conv.dialog_id))
        project_ids = _kb_ids_from_dialog(dialog) if ok and dialog else []
        ok, conv = ConversationService.get_by_id(session_id)
        return _fmt_session(conv, project_ids=project_ids)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/chat/sessions/{session_id}")
async def delete_session(session_id: str, user: AuthUser):
    try:
        from api.db.services.conversation_service import ConversationService
        _get_conv(session_id, user.tenant_id)
        ConversationService.delete_by_id(session_id)
        return {"message": "Session deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _fmt_references(raw) -> dict:
    """Clean RAGFlow reference payload into a consistent, frontend-friendly format."""
    if not raw or not isinstance(raw, dict):
        return {"total": 0, "sources": [], "doc_aggs": []}

    chunks = raw.get("chunks", [])
    clean_chunks = []
    for c in chunks:
        clean_chunks.append({
            "id": c.get("id", ""),
            "content": c.get("content", ""),
            "document_id": c.get("document_id", ""),
            "document_name": c.get("document_name", ""),
            "similarity": round(float(c.get("similarity", 0)), 4),
        })

    doc_aggs = [
        {"document_id": d.get("doc_id", ""), "document_name": d.get("doc_name", ""), "chunk_count": d.get("count", 0)}
        for d in raw.get("doc_aggs", [])
    ]

    return {
        "total": raw.get("total", len(clean_chunks)),
        "sources": clean_chunks,
        "doc_aggs": doc_aggs,
    }


async def _stream_chat(session_id: str, message: str, user_id: str, tenant_id: str) -> AsyncGenerator[str, None]:
    try:
        from api.db.services.conversation_service import ConversationService
        from api.db.services.dialog_service import DialogService

        ok, conv = ConversationService.get_by_id(session_id)
        if not ok or not conv:
            yield f"data: {json.dumps({'type': 'error', 'error': 'Session not found'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        ok, dialog = DialogService.get_by_id(str(conv.dialog_id))
        if not ok or not dialog or str(getattr(dialog, "tenant_id", "")) != tenant_id:
            yield f"data: {json.dumps({'type': 'error', 'error': 'Session not found'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        messages = list(getattr(conv, "message", []) or [])
        messages.append({"role": "user", "content": message})
        ConversationService.update_by_id(session_id, {"message": messages})

        from api.db.services.dialog_service import async_ask
        from api.db.services.user_service import TenantService
        kb_ids = list(getattr(dialog, "kb_ids", []) or [])
        tenant_id = str(getattr(dialog, "tenant_id", ""))
        llm_id = str(getattr(dialog, "llm_id", "") or "")
        if not llm_id:
            _, tenant = TenantService.get_by_id(tenant_id)
            llm_id = str(getattr(tenant, "llm_id", "") or "")

        # Validate rerank provider — but only for providers that actually need a registered
        # API credential (cloud providers like OpenAI/Google/Zhipu). Locally-run models
        # (factory == "LocalHF", e.g. BAAI/bge-reranker-v2-m3 via FlagEmbedding, configured
        # straight from .env — see api/core/config.py:active_rerank_ragflow_id) never get a
        # TenantModelProvider row, because there's no API key to store for them; that's correct,
        # not a misconfiguration. Treating "not registered" as "unusable" for local models was
        # silently disabling reranking on every request that used one.
        rerank_id = getattr(dialog, "rerank_id", "") or ""
        if rerank_id:
            try:
                from api.db.db_models import TenantModelProvider
                parts = rerank_id.split("@")
                rerank_factory = parts[-1] if len(parts) >= 2 else ""
                if rerank_factory and rerank_factory != "LocalHF":
                    exists = TenantModelProvider.select().where(
                        TenantModelProvider.tenant_id == tenant_id,
                        TenantModelProvider.provider_name == rerank_factory,
                    ).count()
                    if not exists:
                        rerank_id = ""
            except Exception:
                rerank_id = ""

        # First-pass reasoning step, run before retrieval: an LLM analyzes the message and
        # decides (a) whether it's pure small talk that should skip RAG entirely, and if not,
        # (b) the best query to hand to the RAG pipeline (a meaning-preserving expansion of the
        # user's message, never a different question), and (c) whether this request needs broad
        # coverage of the knowledge base. Everything after this point — embeddings, hybrid
        # search, reranking, and the final-answer LLM/prompt — is the same unchanged RAG pipeline
        # for every non-greeting request.
        # Pass the prior conversation (everything before the just-appended user message) so the
        # router can resolve follow-ups like "in 3 lines" / "the second one" against context.
        intent = await _classify_intent(message, tenant_id, llm_id or None, history=messages[:-1])

        _rag_log.info(
            "[RAG] router session=%s is_greeting=%s needs_broad_context=%s wants_file_list=%s needs_agent=%s original_query=%r%s",
            session_id, intent["is_greeting"], intent["needs_broad_context"], intent["wants_file_list"], intent.get("needs_agent"), message,
            "" if intent["is_greeting"] or intent["retrieval_query"] == message
            else f" rewritten_query={intent['retrieval_query']!r}",
        )

        if intent["is_greeting"] and intent["reply"].strip():
            reply = intent["reply"].strip()
            yield f"data: {json.dumps({'type': 'delta', 'content': reply})}\n\n"
            messages.append({"role": "assistant", "content": reply, "reference": {}})
            ConversationService.update_by_id(session_id, {"message": messages})
            yield f"data: {json.dumps({'type': 'done', 'answer': reply, 'references': _fmt_references({})})}\n\n"
            yield "data: [DONE]\n\n"
            return

        if intent["wants_file_list"]:
            # File names are metadata, never part of any chunk's embedded content — no amount of
            # retrieval tuning can make semantic/keyword search find "the file is named X.xlsx"
            # inside the file's own content. Answer this directly from the real, authoritative
            # document list instead of routing it through content-based RAG at all.
            from api.db.services.document_service import DocumentService
            names = []
            for kid in kb_ids:
                try:
                    names.extend(d.name for d in DocumentService.query(kb_id=kid, status="1"))
                except Exception:
                    continue
            if names:
                bullet_list = "\n".join(f"- {n}" for n in names)
                reply = f"The following file{'s are' if len(names) != 1 else ' is'} uploaded to this project:\n\n{bullet_list}"
            else:
                reply = "No files have been uploaded to this project yet."
            yield f"data: {json.dumps({'type': 'delta', 'content': reply})}\n\n"
            messages.append({"role": "assistant", "content": reply, "reference": {}})
            ConversationService.update_by_id(session_id, {"message": messages})
            yield f"data: {json.dumps({'type': 'done', 'answer': reply, 'references': _fmt_references({})})}\n\n"
            yield "data: [DONE]\n\n"
            return

        retrieval_query = intent["retrieval_query"]

        # ── Agentic path (additive) ───────────────────────────────────────────
        # Only multi-step analysis tasks (needs_agent, set conservatively by the router) go
        # through the autonomous Analysis Agent: a bounded think→act→observe loop that can
        # search the KB repeatedly with refined queries, run exact computations, and ask the
        # user ONE clarifying question when the request is genuinely ambiguous. ANY failure —
        # timeout, malformed agent output, step exhaustion — falls through to the unchanged
        # RAG pipeline below, so this branch can degrade but never break chat.
        if intent.get("needs_agent"):
            try:
                from api.agents.analysis_agent import run_analysis_agent, AgentUnavailable, WALL_TIMEOUT_SECONDS
                _rag_log.info("[RAG] agent start session=%s query=%r", session_id, message)
                result = await asyncio.wait_for(
                    run_analysis_agent(message, kb_ids, tenant_id, llm_id or None, rerank_id),
                    timeout=WALL_TIMEOUT_SECONDS + 15,  # outer belt over the agent's own inner timeout
                )
                reply = _strip_think(result["answer"])
                refs = result.get("reference") or {}
                yield f"data: {json.dumps({'type': 'delta', 'content': reply})}\n\n"
                messages.append({"role": "assistant", "content": reply, "reference": refs})
                ConversationService.update_by_id(session_id, {"message": messages})
                yield f"data: {json.dumps({'type': 'done', 'answer': reply, 'references': _fmt_references(refs)})}\n\n"
                yield "data: [DONE]\n\n"
                return
            except (AgentUnavailable, asyncio.TimeoutError):
                _rag_log.warning("[RAG] agent unavailable for session=%s — using standard RAG path", session_id)
            except Exception:
                logging.getLogger(__name__).warning("Agent path failed unexpectedly — using standard RAG path", exc_info=True)

        base_similarity_threshold = getattr(dialog, "similarity_threshold", 0.2)
        base_top_k = getattr(dialog, "top_n", 10)
        base_vector_weight = getattr(dialog, "vector_similarity_weight", 0.5)
        # The retrieval engine (rag/nlp/search.py) only ever returns up to `page_size` chunks —
        # 12 by default — no matter how large the knowledge base is. That hard cap is fine for a
        # single-fact lookup, but it silently truncates anything that needs to see many/most rows
        # at once (a full table summary, or a comparison/ranking/"list all" question over
        # spreadsheet-style data). We widen it here, per-request, only when the router flagged
        # broad coverage as necessary.
        if intent["needs_broad_context"]:
            # Overview/summary and aggregate/ranking questions ("tell me the summary", "who has
            # the highest X", "list all Y") rarely share strong vocabulary or semantic similarity
            # with any single chunk, so the normal similarity_threshold filters retrieval down to
            # zero results — which is exactly why these questions used to get "not covered".
            # Setting similarity_threshold to 0 here (only for this request) removes that filter
            # so retrieval returns its top-ranked chunks unconditionally, reliably pulling a much
            # larger, representative slice of real chunks for the unchanged final-answer prompt
            # to work from, instead of returning nothing.
            #
            # IMPORTANT: vector_similarity_weight must NOT be set to 0 to achieve this. In
            # rag/nlp/search.py:rerank_by_model(), that same weight also scales the reranker's
            # actual cross-encoder score before it's added to the final blended score
            # (tkweight*tksim + vtweight*vtsim — vtsim IS the reranker's output). Zeroing it
            # doesn't just bypass the threshold, it also multiplies the reranker's real answer by
            # zero, silently discarding it even though it still runs and costs tokens. Keeping
            # vector_similarity_weight at its normal (positive) value both preserves genuine
            # hybrid vector+term+rerank scoring AND still gets post_threshold=0 (see
            # rag/nlp/search.py: "post_threshold = 0.0 if vector_similarity_weight <= 0 else
            # similarity_threshold" — since similarity_threshold is already 0 here, that branch
            # evaluates to 0 either way).
            similarity_threshold = 0.0
            vector_similarity_weight = base_vector_weight
            top_k = max(base_top_k, 60)
            page_size = 60
            # Cross-encoder reranking is DISABLED for broad-context requests. The reranker's
            # value is precision-ordering the top-10 for a *specific* question; a summary/"list
            # all" request already takes a wide representative slice with threshold 0, so rerank
            # ordering adds ~nothing — but its cost scales with chunk count, and on a CPU-only
            # host cross-encoding 60 chunks (~16k tokens) measured ~30 MINUTES, stalling the
            # request until the browser dropped it ("Failed to fetch") and starving the health
            # check into flagging the container unhealthy. Normal 12-chunk questions keep
            # reranking (seconds, and there precision genuinely matters).
            request_rerank_id = ""
        else:
            similarity_threshold = base_similarity_threshold
            vector_similarity_weight = base_vector_weight
            top_k = base_top_k
            page_size = 12
            request_rerank_id = rerank_id

        search_config = {
            "top_k": top_k,
            "page_size": page_size,
            "similarity_threshold": similarity_threshold,
            "vector_similarity_weight": vector_similarity_weight,
            "rerank_id": request_rerank_id,
            "chat_id": llm_id or None,
            "kb_ids": kb_ids,
        }

        full_answer = ""
        references = []
        think_filter = _ThinkFilter()  # hide any <think>...</think> reasoning from the UI stream
        async for chunk in async_ask(retrieval_query, kb_ids, tenant_id, chat_llm_name=llm_id or None, search_config=search_config):
            if not isinstance(chunk, dict):
                continue
            delta = chunk.get("answer", "")
            is_final = chunk.get("final", False)
            if delta:
                full_answer += delta
                visible = think_filter.feed(delta)
                if visible:
                    yield f"data: {json.dumps({'type': 'delta', 'content': visible})}\n\n"
                    await asyncio.sleep(0)
            if "reference" in chunk and chunk["reference"]:
                references = chunk["reference"]
            if is_final:
                break
        # Emit any tail the filter was still holding, then work with a thinking-free answer for
        # the citation check, history, and the final 'done' payload.
        tail = think_filter.flush()
        if tail:
            yield f"data: {json.dumps({'type': 'delta', 'content': tail})}\n\n"
        full_answer = _strip_think(full_answer)

        # ── Corrective re-retrieval (CRAG-lite) for recall gaps ───────────────────────────────
        # The final-answer LLM inserts "[ID:n]" markers only next to sentences it actually grounded
        # in a retrieved chunk. If a NON-broad answer has ZERO such markers, either nothing relevant
        # exists OR — the failure we want to catch — the narrow search missed content that IS in the
        # documents (a recall gap: a narrowly-phrased question whose answer sits in a chunk the narrow
        # retrieval didn't surface). Before settling on "not covered", retry ONCE with the same
        # wide-net retrieval the summary path uses (threshold 0, large page_size). If that grounds an
        # answer (now carries citations), use it. Uses the model's own citation signal (no hardcoded
        # phrases) and is fully bounded — if the wide retry still doesn't ground, the original honest
        # "not covered" stands.
        if not intent["needs_broad_context"] and "[ID:" not in full_answer:
            try:
                wide_config = {
                    "top_k": max(base_top_k, 60),
                    "page_size": 60,
                    "similarity_threshold": 0.0,
                    "vector_similarity_weight": base_vector_weight,
                    "rerank_id": "",
                    "chat_id": llm_id or None,
                    "kb_ids": kb_ids,
                }
                wide_answer, wide_refs = "", references
                async for chunk in async_ask(retrieval_query, kb_ids, tenant_id, chat_llm_name=llm_id or None, search_config=wide_config):
                    if not isinstance(chunk, dict):
                        continue
                    if chunk.get("answer"):
                        wide_answer += chunk["answer"]
                    if chunk.get("reference"):
                        wide_refs = chunk["reference"]
                    if chunk.get("final"):
                        break
                wide_answer = _strip_think(wide_answer)
                if "[ID:" in wide_answer:  # the wider net actually grounded an answer
                    _rag_log.info("[RAG] corrective re-retrieval recovered a grounded answer session=%s", session_id)
                    full_answer, references = wide_answer, wide_refs
            except Exception:
                logging.getLogger(__name__).warning("Corrective re-retrieval failed — keeping original answer", exc_info=True)

        # Log what retrieval + reranking actually returned — before any later suppression of
        # "sources" for declined answers — so the real chunks and their fused/vector/term scores
        # are visible regardless of what ends up shown to the user. By the time we receive it
        # here, dialog_service.py's decorate_answer has already run chunks_format() on it, so
        # fields are: content, document_id, document_name, similarity (fused score after
        # reranking), vector_similarity, term_similarity (rag/prompts/generator.py:chunks_format).
        raw_chunks = references.get("chunks", []) if isinstance(references, dict) else []
        _rag_log.info(
            "[RAG] retrieval session=%s chunk_count=%d top_chunks=%s",
            session_id, len(raw_chunks),
            [
                {
                    "doc": c.get("document_name", ""),
                    "similarity": round(float(c.get("similarity") or 0), 4),
                    "vector_similarity": round(float(c.get("vector_similarity") or 0), 4),
                    "term_similarity": round(float(c.get("term_similarity") or 0), 4),
                    "preview": (c.get("content") or "")[:80],
                }
                for c in sorted(raw_chunks, key=lambda c: float(c.get("similarity") or 0), reverse=True)[:10]
            ],
        )

        # The final-answer LLM inserts literal "[ID:n]" markers only next to sentences it
        # actually grounded in a retrieved chunk (rag/nlp/search.py: insert_citations). For a
        # genuine document_query answer with zero such markers, the model didn't really use any
        # retrieved content (e.g. it politely declined because nothing relevant was found) —
        # yet the underlying pipeline still attaches whatever weakly-matching chunks were
        # retrieved as "sources" (a fallback in dialog_service.py's decorate_answer). That
        # mismatch is what caused sources to appear under a "not covered" style answer. We
        # detect that mismatch here, using the model's own citation signal rather than
        # matching any specific wording, and drop the sources in that case. Broad/summary and
        # aggregate answers are exempt: they legitimately synthesize/compute across many chunks
        # and often paraphrase rather than quote, so they naturally carry fewer/no citation
        # markers even when genuinely grounded in the retrieved content.
        # ── Verifier Agent (bounded self-correction / reflection) ─────────────
        # Judge the draft against the user's ACTUAL request + retrieved context: does it answer the
        # right thing, honor the requested format/length, stay grounded (no hallucination), and
        # correctly decline out-of-scope questions? If BAD, regenerate ONCE with the verifier's
        # feedback. Run before the citation-based reference drop so the verifier still sees the
        # retrieved chunks for grounding. Fully safe: any verifier error/timeout keeps the original
        # answer — it can slow a reply at worst, never break chat. Toggle via env VERIFIER_ENABLED.
        try:
            from api.agents.verifier_agent import verify_answer
            verdict = await asyncio.wait_for(
                verify_answer(retrieval_query, full_answer, references, tenant_id, llm_id or None),
                timeout=45,
            )
            if verdict.get("verdict") == "bad" and verdict.get("feedback"):
                _rag_log.info("[RAG] verifier=bad session=%s feedback=%r — regenerating once", session_id, verdict["feedback"][:200])
                corrective_q = f"{retrieval_query}\n\n[Answer-quality reviewer feedback you MUST follow: {verdict['feedback']}]"
                new_answer, new_refs = "", references
                async for chunk in async_ask(corrective_q, kb_ids, tenant_id, chat_llm_name=llm_id or None, search_config=search_config):
                    if not isinstance(chunk, dict):
                        continue
                    if chunk.get("answer"):
                        new_answer += chunk["answer"]
                    if chunk.get("reference"):
                        new_refs = chunk["reference"]
                    if chunk.get("final"):
                        break
                new_answer = _strip_think(new_answer)
                if new_answer.strip():
                    full_answer, references = new_answer, new_refs
            else:
                _rag_log.info("[RAG] verifier=good session=%s", session_id)
        except Exception:
            logging.getLogger(__name__).warning("Verifier step failed — keeping original answer", exc_info=True)

        if not intent["needs_broad_context"] and "[ID:" not in full_answer:
            references = {}

        clean_refs = _fmt_references(references)
        messages.append({"role": "assistant", "content": full_answer, "reference": references})
        ConversationService.update_by_id(session_id, {"message": messages})
        yield f"data: {json.dumps({'type': 'done', 'answer': full_answer, 'references': clean_refs})}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as e:
        import logging; logging.getLogger(__name__).exception("Stream chat error")
        yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
        yield "data: [DONE]\n\n"


@router.post("/chat/sessions/{session_id}/messages")
async def send_message(session_id: str, req: ChatRequest, user: AuthUser):
    if req.stream:
        return StreamingResponse(
            _stream_chat(session_id, req.message, user.id, user.tenant_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )
    full = ""
    refs = []
    async for event in _stream_chat(session_id, req.message, user.id, user.tenant_id):
        if event.startswith("data: ") and not event.strip().endswith("[DONE]"):
            try:
                payload = json.loads(event[6:].strip())
                if payload.get("type") == "done":
                    full = payload.get("answer", "")
                    refs = payload.get("references", {})
            except json.JSONDecodeError:
                pass
    return {"answer": full, "references": refs}


@router.get("/chat/sessions/{session_id}/messages")
async def get_messages(session_id: str, user: AuthUser):
    try:
        conv = _get_conv(session_id, user.tenant_id)
        return {"session_id": session_id, "messages": getattr(conv, "message", []) or []}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
