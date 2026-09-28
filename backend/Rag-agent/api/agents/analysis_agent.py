"""
Analysis Agent — the agentic orchestration layer's first agent.

A single autonomous tool-using agent implementing a bounded think → act → observe → decide loop
(ReAct pattern) for complex, multi-step questions that the fixed RAG pipeline cannot answer in
one retrieval pass: cross-document comparison, ranking, counting, and computation over many
records, and multi-source gathering. Simple questions never reach this module — the intent
router in api/routes/chat.py only sets needs_agent=true for genuinely multi-step tasks, and any
failure here falls back to the unchanged RAG path, so this layer is strictly additive.

Design decisions (production guardrails — none of these are optional):
  * MAX_STEPS caps the loop — the agent may re-search / rework, but never unbounded.
  * WALL_TIMEOUT_SECONDS caps total time — on breach we raise AgentUnavailable and the caller
    falls back to plain RAG, so the user always gets an answer.
  * Every observation is truncated to OBS_CHAR_LIMIT so the context (and cost) stays bounded.
  * Grounding: the reasoning prompt forbids answering from model memory; every fact must come
    from a tool observation, and the final answer must name its source documents.
  * Tools are deliberately few (kb_search + compute) — more tools measurably degrade tool-choice
    accuracy; add new ones only with an eval-set check.
  * No new frameworks: reuses LLMBundle (litellm underneath) and settings.retriever — the exact
    same retrieval (hybrid search + rerank) the RAG path uses, wrapped as a callable tool.

The retrieval tool mirrors the retrieval portion of dialog_service.async_ask() rather than
importing RAGFlow's canvas machinery: the canvas/DSL layer expects tenant-configured agent
graphs, which this app doesn't use; calling settings.retriever directly keeps the agent thin,
testable, and independent of vendored orchestration state.
"""
import asyncio
import json
import logging
import re
import time

_log = logging.getLogger("lt_rag_pipeline")

# ── Guardrails ────────────────────────────────────────────────────────────────
MAX_STEPS = 5                # hard cap on tool calls per request
WALL_TIMEOUT_SECONDS = 110   # total wall-clock budget; breach → fallback to plain RAG
OBS_CHAR_LIMIT = 8000        # per-observation truncation (bounds context growth and cost)
MAX_PARSE_RETRIES = 1        # one corrective retry on malformed JSON, then give up to fallback


class AgentUnavailable(Exception):
    """Raised when the agent cannot produce a trustworthy answer (timeout, malformed output,
    step exhaustion without a final answer). The caller falls back to the plain RAG path —
    the user must always receive an answer, never an agent stack trace."""


_AGENT_SYSTEM_PROMPT = (
    "You are an autonomous analysis agent for L&T construction and engineering project documents. "
    "You solve multi-step questions by reasoning and calling tools. You NEVER answer from your own "
    "training knowledge — every fact, figure, and name in your final answer must come from tool results.\n"
    "\n"
    "TOOLS available to you:\n"
    '1. kb_search — search the uploaded project documents. Input: a focused search query. Returns the '
    "most relevant document excerpts with their source document names. Call it multiple times with "
    "different or refined queries if one search does not surface everything you need (e.g. search once "
    "per entity being compared).\n"
    '2. compute — perform exact arithmetic over records you extracted from search results. Input: an '
    'operation ("sum", "avg", "max", "min", "count", "sort_desc", "sort_asc") and a list of records '
    '[{"label": "<name>", "value": <number>}]. Returns the exact result. ALWAYS use this for totals, '
    "rankings, and comparisons instead of doing arithmetic in your head.\n"
    "\n"
    "PROCESS — follow it every turn:\n"
    "1. THINK: break the question into the concrete steps needed. Keep the thought short.\n"
    "2. ACT: choose exactly ONE action for this turn.\n"
    "3. After you receive an OBSERVATION, judge it: does it actually contain what the question needs? "
    "If the excerpts are irrelevant or incomplete, search again with a sharper query (different wording, "
    "specific entity names, table/section terms) instead of settling for weak evidence.\n"
    "4. Before finishing, verify: does your draft answer address the FULL question, is every number "
    "taken from an observation or a compute result, and are the sources named? Only then finish.\n"
    "\n"
    "CLARIFICATION RULE: if the request is genuinely ambiguous or missing information you cannot get "
    "from the documents (e.g. which of two similarly-named items the user means), ask ONE concise "
    "clarifying question using the clarify action instead of guessing. Do NOT clarify when a reasonable "
    "reading exists — prefer acting.\n"
    "\n"
    "HARD RULES:\n"
    "- One action per turn. Never fabricate observations.\n"
    "- For rankings/comparisons: first gather ALL candidate records via kb_search (multiple searches if "
    "needed), then run compute on the real extracted values, then answer with only the records that "
    "genuinely satisfy the asked condition.\n"
    "- If after searching the documents simply do not contain the needed information, say so honestly in "
    "your final answer — never invent values.\n"
    "- Final answers: clear markdown, cite source document names inline, concise and professional.\n"
    "\n"
    "TABLES IN OBSERVATIONS — tables arrive PRE-PARSED as structured grids:\n"
    "1. Tables appear as \"[STRUCTURED TABLE: <title>] (R rows × C cols ...)\" followed by a Markdown "
    "grid. This grid was expanded in code from the source HTML with rowspan/colspan already resolved — "
    "trust its row/column alignment over any guesswork.\n"
    "2. An \"↑\" cell means the value continues from the cell directly above it (expanded from a rowspan) "
    "— resolve it by reading upward in the same column.\n"
    "3. Two grids with the SAME title are one table split across chunks; different titles are different "
    "tables.\n"
    "4. If raw <table> HTML still appears (pre-parsing was impossible for that chunk), parse it "
    "carefully yourself: <caption>=title, <th>=headers, <tr>=rows, <td>=values, expanding rowspan/"
    "colspan before reading any number — and where reconstruction is not possible, apply the corruption "
    "rules below.\n"
    "5. When the user asks to SEE a table, render it as a clean Markdown table in the final answer — "
    "never dump raw HTML or the ↑ markers at the user.\n"
    "\n"
    "TABLE DISCIPLINE — tables in excerpts often come from OCR and may be damaged. Apply these rules to "
    "EVERY value you extract from ANY table:\n"
    "1. Column attribution: identify which column a value belongs to using the table's own headers, and "
    "name that column when you use the value. NEVER compare two values unless you are certain they come "
    "from the SAME column. Reason it out step by step before extracting: 'this row is X; the columns are "
    "A, B, C; the value under column B for row X is N.'\n"
    "2. Corruption check: a table is UNRELIABLE for precise numbers when you see several numbers mashed "
    'into one cell (e.g. "4.20 7.50 4.20 1.30"), headers that don\'t line up with value rows, '
    "or rows whose meaning you cannot reconstruct. Extract from such regions ONLY if the row↔column "
    "mapping is unambiguous; otherwise treat those values as unusable.\n"
    "3. Honest degradation: if the specific values needed are only present in corrupted regions, do NOT "
    "pick numbers anyway — state plainly that the table's structure is damaged in the source and a "
    "precise answer is not reliable, and give whatever partial qualitative answer IS supported.\n"
    "4. Completeness before ranking: before declaring a max/min/highest/lowest, ask yourself 'could more "
    "candidate rows exist that I have not seen?' If the table may continue beyond the excerpt, run "
    "another kb_search with different terms first. Only rank what you actually gathered, and say "
    "'among the records found' in the answer.\n"
    "\n"
    "EXAMPLE (good column reasoning):\n"
    "Observation shows a table with columns [Item, Planned, Actual]. Question: which item has the higher "
    "Actual? Correct: compare only values under 'Actual' (Item A=4.2, Item B=5.1 → B is higher, by 0.9, "
    "both from the 'Actual' column). WRONG: comparing A's 'Planned' 5.0 against B's 'Actual' 5.1 — "
    "different columns, meaningless.\n"
    "EXAMPLE (honest degradation):\n"
    'Observation shows a row where the value cell reads "12.0 7.5 12.0 3.1" with no way to tell which '
    "number belongs to which column. Correct final answer: 'The source table for X is structurally "
    "damaged in the document (values are merged), so a precise comparison is not reliable. What can be "
    "confirmed is that row X exists with values in the 3.1–12.0 range.' WRONG: silently picking 12.0.\n"
    "\n"
    "OUTPUT FORMAT — respond with ONLY one JSON object, no markdown fences, no prose outside it:\n"
    '{"thought": "<brief reasoning>", "action": "kb_search", "query": "<search query>"}\n'
    'OR {"thought": "...", "action": "compute", "operation": "<op>", "records": [{"label": "...", "value": 1.0}]}\n'
    'OR {"thought": "...", "action": "clarify", "question": "<one concise question for the user>"}\n'
    'OR {"thought": "...", "action": "final", "answer": "<complete final answer in markdown>"}'
)


# ── Observation pre-parsing (deterministic HTML-table → structured grid) ─────
#
# LLMs are unreliable HTML parsers — especially for the rowspan/colspan-heavy, OCR-damaged
# tables PDF extraction produces. So tables in retrieved chunks are parsed HERE, in code
# (BeautifulSoup, already a project dependency), expanded into a properly aligned grid, and
# rendered as a clean Markdown table before the LLM ever sees them. The LLM then reasons over
# structured rows/columns instead of mentally reconstructing markup — deterministic, identical
# output for identical input, and generic for any table in any document.
#
# Scope guarantee: this only transforms the OBSERVATION text handed to the agent LLM inside
# this module. Ingestion, the chunk store, the normal RAG path, and citations are untouched.
# Any parse failure returns the original text unchanged — pre-parsing can degrade, never break.

def _expand_table_grid(table) -> list[list[str]]:
    """Expand an HTML table into a rectangular grid honoring rowspan/colspan.

    Standard occupancy-matrix expansion: each cell is placed in the next free column of its
    row; a cell spanning R rows × C cols fills the whole R×C area. The spanning cell's text
    appears once; continuation cells get an "↑" marker (kept compact on purpose — repeating a
    16-row rowspan blob into every row would drown the observation's char budget)."""
    grid: dict[tuple[int, int], str] = {}
    max_col = 0
    rows = table.find_all("tr")
    for r, tr in enumerate(rows):
        c = 0
        for cell in tr.find_all(["td", "th"]):
            while (r, c) in grid:
                c += 1
            try:
                rowspan = min(int(cell.get("rowspan", 1) or 1), len(rows))
                colspan = min(int(cell.get("colspan", 1) or 1), 100)
            except (TypeError, ValueError):
                rowspan, colspan = 1, 1
            text = " ".join(cell.get_text(" ", strip=True).split())
            for dr in range(rowspan):
                for dc in range(colspan):
                    grid[(r + dr, c + dc)] = text if (dr == 0 and dc == 0) else "↑"
            max_col = max(max_col, c + colspan)
            c += colspan
    return [[grid.get((r, c), "") for c in range(max_col)] for r in range(len(rows))]


def _render_tables_for_llm(content: str) -> str:
    """Replace every <table> in a chunk with a deterministic Markdown rendering of its
    expanded grid; all non-table text is preserved as-is. Returns the input unchanged on any
    parsing problem — a damaged chunk must never fail the search tool."""
    if "<table" not in content.lower():
        return content
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return content
        for idx, table in enumerate(tables):
            grid = _expand_table_grid(table)
            grid = [row for row in grid if any(cell.strip() for cell in row)]
            if not grid:
                table.replace_with("")
                continue
            caption = table.find("caption")
            title = " ".join(caption.get_text(" ", strip=True).split()) if caption else f"table {idx + 1}"
            width = max(len(row) for row in grid)
            lines = [f"\n[STRUCTURED TABLE: {title}] ({len(grid)} rows × {width} cols; \"↑\" = cell "
                     "continues the value from the row above, expanded from a rowspan)"]
            for r, row in enumerate(grid):
                cells = [cell.replace("|", "/") for cell in row] + [""] * (width - len(row))
                lines.append("| " + " | ".join(cells) + " |")
                if r == 0:
                    lines.append("|" + "---|" * width)
            table.replace_with("\n".join(lines) + "\n")
        return soup.get_text()
    except Exception:
        return content  # degrade to raw text; the prompt's HTML rules still apply


# ── Tools ─────────────────────────────────────────────────────────────────────

async def _kb_search(query: str, kb_ids: list, tenant_id: str, rerank_id: str, state: dict) -> str:
    """Hybrid search + rerank over the project's knowledge bases — the same retrieval the RAG
    path uses (mirrors the retrieval portion of dialog_service.async_ask). Accumulates raw
    chunks/doc_aggs into `state` so the final answer can ship real citations."""
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from api.db.joint_services.tenant_model_service import get_model_config_from_provider_instance
    from common.constants import LLMType
    from common import settings as _cs

    kbs = KnowledgebaseService.get_by_ids(kb_ids)
    if not kbs:
        return "ERROR: no knowledge base available."
    embedding_list = list({kb.embd_id for kb in kbs})
    embd_owner = kbs[0].tenant_id
    embd_mdl = LLMBundle(embd_owner, get_model_config_from_provider_instance(embd_owner, LLMType.EMBEDDING, embedding_list[0]))
    # Cross-encoder reranking is OFF by default for agent searches: each rerank of a 12-chunk
    # page costs tens of seconds on a CPU-only host, and the agent may search several times per
    # request — that alone would blow the WALL_TIMEOUT budget. The agent's searches are
    # gathering/recall-oriented (it reads all returned excerpts itself), so hybrid vector+BM25
    # fused ordering is sufficient. On a GPU server set AGENT_RERANK=1 to re-enable.
    import os
    rerank_mdl = None
    if rerank_id and os.getenv("AGENT_RERANK", "0") == "1":
        try:
            rerank_mdl = LLMBundle(tenant_id, get_model_config_from_provider_instance(tenant_id, LLMType.RERANK, rerank_id))
        except Exception:
            rerank_mdl = None  # rerank is an enhancement, never a blocker

    kbinfos = await _cs.retriever.retrieval(
        question=query,
        embd_mdl=embd_mdl,
        tenant_ids=list({kb.tenant_id for kb in kbs}),
        kb_ids=kb_ids,
        page=1,
        page_size=12,
        similarity_threshold=0.1,
        vector_similarity_weight=0.5,
        top=1024,
        doc_ids=[],
        aggs=True,
        rerank_mdl=rerank_mdl,
    )
    chunks = kbinfos.get("chunks", []) or []
    # Accumulate for citations, deduped by chunk id across all searches this run.
    for c in chunks:
        cid = c.get("chunk_id") or c.get("id") or id(c)
        if cid not in state["seen_chunk_ids"]:
            state["seen_chunk_ids"].add(cid)
            state["chunks"].append(c)
    for d in kbinfos.get("doc_aggs", []) or []:
        did = d.get("doc_id")
        if did and did not in state["seen_doc_ids"]:
            state["seen_doc_ids"].add(did)
            state["doc_aggs"].append(d)

    if not chunks:
        return "No relevant excerpts found for this query. Try a different or more specific query."
    lines = []
    for i, c in enumerate(chunks):
        doc = c.get("docnm_kwd") or c.get("document_name") or "unknown document"
        content = (c.get("content_with_weight") or c.get("content") or "").strip()
        # Deterministically convert any HTML tables into aligned structured grids before the
        # LLM sees them (see _render_tables_for_llm above).
        content = _render_tables_for_llm(content)
        lines.append(f"[{i}] (source: {doc})\n{content}")
    return ("\n\n".join(lines))[:OBS_CHAR_LIMIT]


def _compute(operation: str, records: list) -> str:
    """Exact, safe aggregation over labeled numeric records. Pure Python — no eval, no code
    execution — so a hallucinated payload can at worst produce an error string, never run code."""
    op = str(operation or "").strip().lower()
    cleaned = []
    for r in records or []:
        try:
            cleaned.append((str(r.get("label", "?")), float(r.get("value"))))
        except (TypeError, ValueError):
            continue
    if not cleaned:
        return "ERROR: no valid numeric records supplied. Provide records as [{label, value}]."
    values = [v for _, v in cleaned]
    if op == "sum":
        return f"sum = {sum(values):g} (over {len(values)} records)"
    if op == "avg":
        return f"avg = {sum(values) / len(values):g} (over {len(values)} records)"
    if op == "count":
        return f"count = {len(values)}"
    if op in ("max", "min"):
        lbl, val = (max if op == "max" else min)(cleaned, key=lambda kv: kv[1])
        return f"{op} = {val:g} ({lbl})"
    if op in ("sort_desc", "sort_asc"):
        ordered = sorted(cleaned, key=lambda kv: kv[1], reverse=(op == "sort_desc"))
        return "sorted: " + "; ".join(f"{lbl}={val:g}" for lbl, val in ordered)
    return f"ERROR: unknown operation '{op}'. Use sum/avg/max/min/count/sort_desc/sort_asc."


def _merge_references(state: dict) -> dict:
    """Shape the accumulated retrieval results like async_ask's reference payload so
    chat.py's _fmt_references / frontend citation rendering work unchanged."""
    try:
        from rag.prompts.generator import chunks_format
        formatted = chunks_format({"chunks": state["chunks"]})
    except Exception:
        formatted = []
    return {"chunks": formatted, "doc_aggs": state["doc_aggs"]}


# ── The agent loop ────────────────────────────────────────────────────────────

async def run_analysis_agent(question: str, kb_ids: list, tenant_id: str,
                             llm_id: str | None, rerank_id: str) -> dict:
    """Run the bounded think→act→observe loop. Returns
        {"answer": str, "reference": dict, "clarify": bool, "steps": int}
    Raises AgentUnavailable on timeout / malformed output / step exhaustion, which the caller
    treats as "use the plain RAG path instead"."""
    from api.db.services.llm_service import LLMBundle
    from api.db.joint_services.tenant_model_service import get_model_config_from_provider_instance
    from common.constants import LLMType

    model_config = get_model_config_from_provider_instance(tenant_id, LLMType.CHAT, llm_id or None)
    mdl = LLMBundle(tenant_id, model_config)

    state = {"chunks": [], "doc_aggs": [], "seen_chunk_ids": set(), "seen_doc_ids": set()}
    convo = [{"role": "user", "content": f"Question: {question}"}]
    started = time.monotonic()
    parse_retries = 0

    for step in range(1, MAX_STEPS + 1):
        if time.monotonic() - started > WALL_TIMEOUT_SECONDS:
            _log.warning("[RAG] agent timeout after %d steps — falling back to RAG", step - 1)
            raise AgentUnavailable("wall timeout")

        txt = await mdl.async_chat(_AGENT_SYSTEM_PROMPT, convo, {"temperature": 0.0})
        # Strip <think>...</think> — reasoning models (e.g. Qwen3 via Ollama) emit a thinking block
        # that can contain braces and would break the find("{")..rfind("}") JSON extraction below.
        txt = re.sub(r"<think>.*?</think>", "", (txt or ""), flags=re.DOTALL).strip()
        start, end = txt.find("{"), txt.rfind("}")
        try:
            decision = json.loads(txt[start:end + 1]) if start != -1 and end != -1 else None
        except json.JSONDecodeError:
            decision = None
        if not isinstance(decision, dict) or not decision.get("action"):
            if parse_retries < MAX_PARSE_RETRIES:
                parse_retries += 1
                convo.append({"role": "assistant", "content": txt})
                convo.append({"role": "user", "content": "Your reply was not a single valid JSON action object. Respond again with ONLY the JSON object in the required format."})
                continue
            _log.warning("[RAG] agent produced unparseable output — falling back to RAG")
            raise AgentUnavailable("malformed agent output")

        action = str(decision.get("action", "")).lower()
        thought = str(decision.get("thought", ""))[:300]
        _log.info("[RAG] agent step=%d action=%s thought=%r", step, action, thought)
        convo.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)})

        if action == "final":
            answer = str(decision.get("answer", "")).strip()
            if not answer:
                raise AgentUnavailable("empty final answer")
            _log.info("[RAG] agent done steps=%d chunks_gathered=%d", step, len(state["chunks"]))
            return {"answer": answer, "reference": _merge_references(state), "clarify": False, "steps": step}

        if action == "clarify":
            q = str(decision.get("question", "")).strip()
            if not q:
                raise AgentUnavailable("empty clarify question")
            _log.info("[RAG] agent asking user for clarification: %r", q[:200])
            return {"answer": q, "reference": {}, "clarify": True, "steps": step}

        if action == "kb_search":
            obs = await _kb_search(str(decision.get("query", "")).strip() or question,
                                   kb_ids, tenant_id, rerank_id, state)
        elif action == "compute":
            obs = _compute(decision.get("operation"), decision.get("records"))
        else:
            obs = f"ERROR: unknown action '{action}'. Valid actions: kb_search, compute, clarify, final."

        convo.append({"role": "user", "content": f"OBSERVATION:\n{obs[:OBS_CHAR_LIMIT]}"})

    # Step budget exhausted without a final answer: one last bounded chance to conclude from
    # what was gathered, else hand the request back to the plain RAG path.
    convo.append({"role": "user", "content": "You have used all available steps. Give your FINAL answer now from the observations above (action \"final\"). If they are insufficient, state honestly what is missing."})
    txt = await mdl.async_chat(_AGENT_SYSTEM_PROMPT, convo, {"temperature": 0.0})
    txt = re.sub(r"<think>.*?</think>", "", (txt or ""), flags=re.DOTALL).strip()
    start, end = txt.find("{"), txt.rfind("}")
    try:
        decision = json.loads(txt[start:end + 1]) if start != -1 and end != -1 else {}
    except json.JSONDecodeError:
        decision = {}
    answer = str(decision.get("answer", "")).strip()
    if decision.get("action") == "final" and answer:
        _log.info("[RAG] agent done (forced final) steps=%d", MAX_STEPS)
        return {"answer": answer, "reference": _merge_references(state), "clarify": False, "steps": MAX_STEPS}
    _log.warning("[RAG] agent exhausted steps without final answer — falling back to RAG")
    raise AgentUnavailable("step budget exhausted")
