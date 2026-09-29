from langgraph.types import Send
from web_search_agent.card import CARD, WebSearchParams
from web_search_agent.nodes.finalize import step_result
from web_search_agent.nodes.plan_queries import question_from_task, upstream_hints
from web_search_agent.routing import fan_out_fetch, fan_out_search
from web_search_agent.services.chunker import chunk_text
from web_search_agent.services.reranker import Candidate, Reranker
from web_search_agent.services.urls import domain_matches, get_domain, normalize_url
from web_search_agent.settings import Settings
from web_search_agent.state import merge_spans
from web_search_agent.steps import ordered_steps, plural, timings

from utils import AgentTask
from web_search_agent import prompts


def test_chunker_respects_size_and_overlap():
    paragraphs = [" ".join(f"p{i}w{j}" for j in range(60)) for i in range(10)]
    chunks = chunk_text("\n\n".join(paragraphs), chunk_size=150, overlap=60, max_chunks=20)
    assert len(chunks) > 1
    assert all(len(c.split()) <= 150 for c in chunks)
    assert chunks[0].split()[-1] == "p1w59" and chunks[1].split()[0] == "p1w0"


def test_chunker_keeps_short_page():
    assert chunk_text("Only a short line.") == ["Only a short line."]


def test_url_helpers():
    assert get_domain("https://www.BBC.co.uk/news") == "bbc.co.uk"
    assert normalize_url("https://www.a.com/x/#top") == normalize_url("http://a.com/x")
    assert domain_matches("news.reuters.com", ["reuters.com"])
    assert not domain_matches("notreuters.com", ["reuters.com"])


def test_bm25_fallback_ranks_relevant_first_and_limits_per_source():
    reranker = Reranker(Settings(max_chunks_per_source=1, recency_weight=0.0))
    reranker._load_attempted = True
    candidates = [
        Candidate(text="Recipes for chocolate cake", source_key="1"),
        Candidate(text="Solid-state batteries promise higher energy density", source_key="2"),
        Candidate(text="Solid-state batteries: new electrolyte breakthrough", source_key="2"),
        Candidate(text="Lithium solid-state battery startup raises funding", source_key="3"),
    ]
    ranked = reranker.rerank("solid-state batteries", candidates, top_k=3)
    assert reranker.active_name == "bm25"
    assert ranked[0].candidate.source_key in {"2", "3"}
    assert [r.candidate.source_key for r in ranked].count("2") == 1


def test_rerank_without_cross_encoder_never_loads_the_model():
    reranker = Reranker(Settings())
    reranker.rerank("q", [Candidate(text="q text", source_key="1")], top_k=1, cross_encoder=False)
    assert not reranker.loaded and reranker.load_error is None


def test_merge_spans_keeps_earliest_start_and_latest_end():
    merged = merge_spans({"search": {"start": 5, "end": 7}},
                         {"search": {"start": 4, "end": 6}, "extract": {"start": 8, "end": 9}})
    assert merged == {"search": {"start": 4, "end": 7}, "extract": {"start": 8, "end": 9}}


def test_steps_order_and_timings_in_seconds():
    state = {"search": {"id": "search", "title": "Web search", "status": "done", "duration_s": 1.5, "detail": "",
                        "items": []}}
    ordered = ordered_steps(state)
    assert [s["id"] for s in ordered] == ["plan", "search", "extract", "chunk", "rerank", "verify"]
    assert ordered[0]["status"] == "pending"
    assert timings(state, 3.456) == {"plan_s": 0.0, "search_s": 1.5, "extract_s": 0.0, "chunk_s": 0.0,
                                     "rerank_s": 0.0, "total_s": 3.46}
    assert plural(1, "query", "queries") == "1 query" and plural(3, "query", "queries") == "3 queries"


def test_fan_outs_send_one_task_each():
    sends = fan_out_search({"queries": ["a", "b"], "effective_freshness": "week", "include_domains": ["x.com"]})
    assert [s.node for s in sends] == ["search", "search"]
    assert sends[1].arg == {"index": 1, "query": "b", "freshness": "week", "include_domains": ["x.com"],
                            "exclude_domains": []}
    assert fan_out_fetch({"hits": [], "fetch_urls": []}) == "finalize"
    assert fan_out_fetch({"hits": [{"url": "https://s"}], "fetch_urls": []}) == "rank"  # sample hits
    assert fan_out_fetch({"hits": [{}], "fetch_urls": ["https://a", "https://b"]}) == [
        Send("extract", {"url": "https://a"}), Send("extract", {"url": "https://b"})]


def test_question_from_task_uses_query_and_region():
    def question(objective, **params):
        return question_from_task(AgentTask(task_id="s1", objective=objective), WebSearchParams(**params))

    assert question("What is the price of iPhone?") == "What is the price of iPhone?"
    assert question("Find iPhone price in Oman", query="iPhone price", region="Oman") == "iPhone price in Oman"
    assert question("iPhone price in Oman", region="oman") == "iPhone price in Oman"  # not added twice


def test_step_result_keeps_the_question_and_the_top_n_contents():
    evidence = [{"title": f"T{i}", "url": f"https://x.com/{i}", "content": f"passage  {i}\n"} for i in range(1, 6)]
    result = step_result("iPhone price in Oman", evidence, 3)
    assert result == {
        "status": "ok",
        "summary": ("Question: iPhone price in Oman\n\nTop 3 web results:\n\n"
                    "[1] T1 - https://x.com/1\npassage 1\n\n[2] T2 - https://x.com/2\npassage 2\n\n"
                    "[3] T3 - https://x.com/3\npassage 3"),
        "question": "iPhone price in Oman",
        "findings": [{"rank": i, "title": f"T{i}", "url": f"https://x.com/{i}", "content": f"passage {i}"}
                     for i in (1, 2, 3)],
        "sources": ["https://x.com/1", "https://x.com/2", "https://x.com/3"],
    }
    assert step_result("q", [], 3)["status"] == "failed"


def test_upstream_hints_from_a_rag_result():
    queries, known = upstream_hints({
        "s1": {"status": "ok", "summary": "Leave: 30 days.", "search_query": "UAE leave law",
               "search_queries": ["uae leave law", "UAE public holidays 2026"]},
        "s2": "not a dict",
        "s3": {"status": "ok", "answer": "Answer from docs", "summary": "ignored when answer is set"},
    })
    assert queries == ["UAE leave law", "UAE public holidays 2026"]  # de-duplicated, case-insensitive
    assert known == "[s1] Leave: 30 days.\n\n[s3] Answer from docs"
    assert upstream_hints({}) == ([], "")


def test_prompts_render_without_leftover_placeholders():
    rendered = prompts.render("plan_queries", max_queries=3, today="2026-09-26")
    assert "$" not in rendered and "2026-09-26" in rendered


def test_settings_are_prefixed_for_the_shared_env_file(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDERS", "tavily,duckduckgo")
    monkeypatch.setenv("TAVILY_API_KEY", "not-ours")  # un-prefixed keys belong to other agents
    settings = Settings()
    assert settings.provider_order == ["tavily", "duckduckgo"] and not settings.offline
    assert settings.tavily_api_key is None
    assert Settings(providers="sample").offline


def test_card_is_a_platform_agent_card():
    assert CARD.name == "web_search" and CARD.approval_mode == "none"
    assert len(CARD.examples) >= 2
    props = CARD.output_schema["properties"]
    assert set(props) == {"status", "summary", "question", "findings", "sources"}
    assert props["sources"]["items"] == {"type": "string"}
    assert "rag" in CARD.when_to_use.lower()


def test_agent_env_file_wins_over_backend_env_but_not_over_real_env(tmp_path, monkeypatch):
    from web_search_agent.settings import load_agent_env

    shared = tmp_path / "backend.env"
    shared.write_text("WEB_SEARCH_PROVIDERS=sample\n", encoding="utf-8")
    agent = tmp_path / "agent.env"
    agent.write_text("WEB_SEARCH_PROVIDERS=tavily\nWEB_SEARCH_TAVILY_API_KEY=from-agent\nWEB_SEARCH_SEARXNG_URL=x\n",
                     encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(shared))
    monkeypatch.setenv("WEB_SEARCH_ENV_FILE", str(agent))
    monkeypatch.setenv("WEB_SEARCH_PROVIDERS", "sample")  # as loaded by utils.env from backend/.env
    monkeypatch.setenv("WEB_SEARCH_SEARXNG_URL", "real")  # a real environment variable
    monkeypatch.delenv("WEB_SEARCH_TAVILY_API_KEY", raising=False)

    load_agent_env()
    settings = Settings()
    assert settings.provider_order == ["tavily"]  # agent file beats backend/.env
    assert settings.tavily_api_key == "from-agent"  # unset before -> taken from the agent file
    assert settings.searxng_url == "real"  # real env var beats the agent file


def test_top_contents_come_from_different_pages_where_possible():
    from web_search_agent.nodes.finalize import top_contents

    def e(url, text):
        return {"title": url, "url": url, "content": text}

    ranked = [e("https://w/a", "a1"), e("https://w/a", "a2"), e("https://w/b", "b1"), e("https://w/c", "c1")]
    assert [c["content"] for c in top_contents(ranked, 3)] == ["a1", "b1", "c1"]  # not a1, a2, b1
    only_two_pages = [e("https://w/a", "a1"), e("https://w/a", "a2"), e("https://w/b", "b1")]
    assert [c["content"] for c in top_contents(only_two_pages, 3)] == ["a1", "a2", "b1"]  # reranker order kept
    assert [c["rank"] for c in top_contents(only_two_pages, 3)] == [1, 2, 3]
