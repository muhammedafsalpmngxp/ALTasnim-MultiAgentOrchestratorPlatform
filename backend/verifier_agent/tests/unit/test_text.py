"""The answer's text and the model settings: never raises on an unexpected shape."""

import pytest
from verifier_agent.text import cut, text_of

from verifier_agent import llm, settings


def test_answer_first_then_summary_then_text():
    assert text_of({"answer": "A", "summary": "S"}) == "A"
    assert text_of({"summary": " S "}) == "S"
    assert text_of({"text": "T"}) == "T"


@pytest.mark.parametrize("out", [None, "", [], {}, {"answer": None}])
def test_empty_shapes(out):
    assert text_of(out) == ""


def test_cut():
    assert cut("abc", 5) == "abc" and cut("abcdef", 3).startswith("abc\n[… cut")


def test_model_name(monkeypatch):
    monkeypatch.setenv("VERIFIER_LLM_MODEL", " gpt-4o-mini ")
    assert settings.model_name() == "openai:gpt-4o-mini"
    monkeypatch.setenv("VERIFIER_LLM_MODEL", "anthropic:claude-x")
    assert settings.model_name() == "anthropic:claude-x"
    monkeypatch.setenv("VERIFIER_LLM_MODEL", "")
    assert settings.model_name() is None and llm.judge_model() is None


def test_reasoning_models_get_no_temperature(monkeypatch):
    seen = {}

    def fake_init(name, **kwargs):
        seen[name] = kwargs
        return object()

    monkeypatch.setattr("langchain.chat_models.init_chat_model", fake_init)
    llm._build.cache_clear()
    llm._build("openai:gpt-5.6-luna")
    llm._build("openai:gpt-4o-mini")
    llm._build.cache_clear()
    assert "temperature" not in seen["openai:gpt-5.6-luna"] and seen["openai:gpt-4o-mini"]["temperature"] == 0
    assert seen["openai:gpt-4o-mini"]["use_responses_api"] is True
