"""The email the agent writes and how it is sent: content only from the earlier steps, the LLM checked against it,
the professional layout, recipients' rules, edits, SMTP (STARTTLS + login), errors, and no double send.
No network: a fake LLM and a fake SMTP server."""

import smtplib
import uuid

import pytest
from communication_agent.api import app
from communication_agent.channels import email as channel
from communication_agent.graph import build_graph
from communication_agent.render import EmailContent
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from communication_agent import writer
from utils import AgentTask

SEARCH = {"status": "ok", "summary": "iPhone 16 (128 GB) costs OMR 299 at Example Store.",
          "sources": ["https://example.com/oman"]}
ANSWER = {"status": "ok", "answer": "The iPhone 16 costs **OMR 299** in Oman.", "sources": ["https://example.com/oman"]}
VERDICT = {"status": "ok", "passed": True, "summary": "Verification passed"}


def task(params=None, inputs=None):
    return AgentTask(task_id="m1", objective="Email the iPhone 16 price in Oman",
                     params=params or {"to": ["rijin@gmail.com"]},
                     inputs={"s1": SEARCH, "v1": VERDICT, "s2": ANSWER} if inputs is None else inputs).model_dump()


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for name in ("COMMUNICATION_LLM_MODEL", "EMAIL_DELIVERY", "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME",
                 "SMTP_PASSWORD", "SMTP_USE_TLS", "EMAIL_FROM", "EMAIL_FROM_NAME", "EMAIL_SIGNATURE",
                 "EMAIL_ALLOWED_DOMAINS", "EMAIL_MAX_RECIPIENTS", "EMAIL_REPLY_TO"):
        monkeypatch.delenv(name, raising=False)
    channel.SENT.clear()
    writer._model.cache_clear()


def run(params=None, inputs=None, store=None):
    graph = build_graph().copy(update={"checkpointer": InMemorySaver(), "store": store})
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    return graph, config, graph.invoke({"task": task(params, inputs)}, config)


def draft_of(out):
    return out["__interrupt__"][0].value["draft"]


class FakeLLM:
    def __init__(self, *emails):
        self.emails = list(emails)
        self.prompts = []

    def with_structured_output(self, schema, method=None):
        return self

    def invoke(self, messages):
        self.prompts.append(messages)
        item = self.emails.pop(0)
        if isinstance(item, Exception):
            raise item
        return EmailContent.model_validate(item)


GOOD = {"subject": "iPhone 16 price in Oman", "greeting": "Dear Rijin,",
        "opening": "Please find below the iPhone 16 price you requested.",
        "paragraphs": ["The iPhone 16 costs **OMR 299** in Oman."],
        "closing": "Please let me know if you need further details."}


def use_llm(monkeypatch, fake):
    monkeypatch.setenv("COMMUNICATION_LLM_MODEL", "gpt-test")
    monkeypatch.setattr(writer, "_model", lambda name: fake)


# ---- content and layout ------------------------------------------------ #

def test_without_a_model_the_template_has_the_content_signature_and_sources():
    _, _, out = run()
    d = draft_of(out)
    assert d["writer"] == "template" and d["to"] == ["rijin@gmail.com"]
    body = d["body"]
    assert body.startswith("Hello,") and "costs OMR 299 in Oman" in body  # the final answer, bold removed
    assert "Verification passed" not in body  # a verdict is a check, not content
    assert "Best regards,\nALTasnim Agent Platform" in body
    assert "Sources\n1. https://example.com/oman" in body and "Prepared by" not in body  # no bulk-mail footer
    assert "<strong>OMR 299</strong>" in d["html"] and "<script" not in d["html"]


def test_the_llm_writes_the_email_and_every_fact_is_checked(monkeypatch):
    fake = FakeLLM(GOOD)
    use_llm(monkeypatch, fake)
    _, _, out = run({"to": ["rijin@gmail.com"], "recipient_name": "Rijin"})
    d = draft_of(out)
    assert (d["writer"], d["grounded"], d["subject"]) == ("llm", True, "iPhone 16 price in Oman")
    assert d["body"].startswith("Dear Rijin,") and "**" not in d["body"]
    human = fake.prompts[0][1].content
    assert "CONTENT (the only facts you may use)" in human and "OMR 299" in human
    assert "Verification passed" not in human


def test_an_invented_number_goes_back_to_the_llm_once(monkeypatch):
    invented = {**GOOD, "paragraphs": ["The iPhone 16 costs **OMR 249** after a discount."]}
    fake = FakeLLM(invented, GOOD)
    use_llm(monkeypatch, fake)
    _, _, out = run()
    assert draft_of(out)["writer"] == "llm" and "OMR 299" in draft_of(out)["body"]
    assert "number 249" in fake.prompts[1][-1].content  # told what is not in the content


def test_still_invented_or_llm_down_falls_back_to_the_template(monkeypatch):
    invented = {**GOOD, "paragraphs": ["Call https://scam.example for OMR 1 discount, price 249."]}
    use_llm(monkeypatch, FakeLLM(invented, invented))
    _, _, out = run()
    assert draft_of(out)["writer"] == "template" and "249" not in draft_of(out)["body"]

    use_llm(monkeypatch, FakeLLM(TimeoutError("api down")))
    _, _, out = run()
    assert draft_of(out)["writer"] == "template"


def test_the_users_subject_is_kept(monkeypatch):
    use_llm(monkeypatch, FakeLLM(GOOD))
    _, _, out = run({"to": ["rijin@gmail.com"], "subject": "Prices for the board"})
    assert draft_of(out)["subject"] == "Prices for the board"


# ---- recipients and content rules -------------------------------------- #

def test_invalid_recipients_or_nothing_to_send_fail_before_any_draft(monkeypatch):
    _, _, out = run({"to": ["not-an-email"]})
    assert out["result"]["status"] == "failed" and "not an email address: not-an-email" in out["result"]["summary"]

    _, _, out = run(inputs={"v1": VERDICT})
    assert out["result"]["status"] == "failed" and "no content to send" in out["result"]["summary"]

    monkeypatch.setenv("EMAIL_ALLOWED_DOMAINS", "altasnim.com")
    _, _, out = run()
    assert "not allowed (EMAIL_ALLOWED_DOMAINS): rijin@gmail.com" in out["result"]["summary"]

    monkeypatch.delenv("EMAIL_ALLOWED_DOMAINS")
    monkeypatch.setenv("EMAIL_MAX_RECIPIENTS", "1")
    _, _, out = run({"to": ["a@x.com"], "cc": ["b@x.com"]})
    assert "at most 1" in out["result"]["summary"]


def test_an_edited_body_gets_a_new_html_and_a_bad_edit_is_not_sent(monkeypatch):
    sent = []
    monkeypatch.setattr("communication_agent.nodes.send.send_email", lambda d: sent.append(d) or "id")
    graph, config, _ = run()
    out = graph.invoke(Command(resume={"action": "edit", "edited": {
        "subject": "Price", "cc": ["boss@x.com"], "body": "Hello,\n\n- OMR 299\n- 128 GB\n\nThanks"}}), config)
    assert out["result"]["status"] == "ok" and out["result"]["cc"] == ["boss@x.com"]
    assert "<li" in sent[0].html and "OMR 299" in sent[0].html and sent[0].subject == "Price"

    graph, config, _ = run()
    out = graph.invoke(Command(resume={"action": "edit", "edited": {"to": ["oops"]}}), config)
    assert out["result"]["status"] == "failed" and len(sent) == 1


# ---- SMTP -------------------------------------------------------------- #

class FakeSMTP:
    instances = []
    fail = []  # exceptions to raise on send_message, in order

    def __init__(self, host, port, timeout=None, **_):
        self.host, self.port, self.calls, self.sent = host, port, [], []
        FakeSMTP.instances.append(self)

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user))
        if password == "wrong":
            raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")

    def send_message(self, msg, from_addr=None, to_addrs=None):
        if FakeSMTP.fail:
            raise FakeSMTP.fail.pop(0)
        self.sent.append((msg, from_addr, to_addrs))
        return {}

    def quit(self):
        self.calls.append("quit")


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.fail = [], []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(channel.time, "sleep", lambda s: None)
    for name, value in {"SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587", "SMTP_USERNAME": "me@gmail.com",
                        "SMTP_PASSWORD": "app-password", "SMTP_USE_TLS": "true"}.items():
        monkeypatch.setenv(name, value)
    return FakeSMTP


def approve_and_send(store=None):
    graph, config, _ = run(store=store)
    return graph, config, graph.invoke(Command(resume={"action": "approve"}), config)


def test_smtp_uses_starttls_and_login_and_sends_text_and_html(smtp):
    _, _, out = approve_and_send()
    assert out["result"]["status"] == "ok" and out["result"]["channel"] == "smtp"
    server = smtp.instances[0]
    assert (server.host, server.port) == ("smtp.gmail.com", 587)
    assert server.calls[:4] == ["ehlo", "starttls", "ehlo", ("login", "me@gmail.com")]
    msg, from_addr, to_addrs = server.sent[0]
    assert from_addr == "me@gmail.com" and to_addrs == ["rijin@gmail.com"]
    assert msg["From"] == "ALTasnim Agent Platform <me@gmail.com>" and msg["Message-ID"] is None  # Gmail sets it
    assert [p.get_content_type() for p in msg.iter_parts()] == ["text/plain", "text/html"]
    assert channel.SENT[0]["to"] == ["rijin@gmail.com"]


def test_a_wrong_password_fails_clearly_without_retry(smtp, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "wrong")
    _, _, out = approve_and_send()
    assert out["result"]["status"] == "failed"
    assert "rejected the login for me@gmail.com" in out["result"]["summary"] and "App Password" in out["result"][
        "summary"]
    assert len(smtp.instances) == 1


def test_a_temporary_error_is_tried_again_and_sent_once(smtp):
    smtp.fail = [smtplib.SMTPServerDisconnected("connection lost")]
    _, _, out = approve_and_send()
    assert out["result"]["status"] == "ok"
    assert sum(len(s.sent) for s in smtp.instances) == 1 and len(smtp.instances) == 2


def test_a_resumed_run_on_the_same_thread_does_not_send_again(smtp):
    store = InMemoryStore()
    graph, config, first = approve_and_send(store)
    graph.invoke({"task": task()}, config)  # the same run again (e.g. a retry)
    again = graph.invoke(Command(resume={"action": "approve"}), config)
    assert again["result"]["message_id"] == first["result"]["message_id"]
    assert sum(len(s.sent) for s in smtp.instances) == 1


def test_not_configured_smtp_is_a_clear_failure(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    _, _, out = approve_and_send()
    assert out["result"]["status"] == "failed"
    assert "set SMTP_USERNAME, SMTP_PASSWORD" in out["result"]["summary"]


def test_console_delivery_logs_only(monkeypatch, smtp):
    monkeypatch.setenv("EMAIL_DELIVERY", "console")
    _, _, out = approve_and_send()
    assert out["result"]["channel"] == "console" and "logged only" in out["result"]["summary"]
    assert smtp.instances == []


def test_status_shows_the_setup_but_never_the_password(smtp):
    client = TestClient(app)
    body = client.get("/custom/status").json()
    assert body["ready"] is True and body["security"] == "starttls" and body["password_set"] is True
    assert "app-password" not in str(body)
    assert client.get("/custom/sent").json() == []


# ---- the user's own text ------------------------------------------------ #

USER_TEXT = ("Hello,\n\nThe current India price is Rs 1,64,900.\n\nBest regards,\nALTasnim Agent Platform\n\n"
             "Sources:\nhttps://example.com/a")


def test_the_users_own_text_is_sent_exactly_as_written_without_earlier_steps(monkeypatch):
    fake = FakeLLM()  # must not be called
    use_llm(monkeypatch, fake)
    params = {"to": ["rijin@gmail.com"], "cc": ["boss@x.com"], "subject": "iPhone 18 Pro India price",
              "body": USER_TEXT}
    _, _, out = run(params, inputs={})
    d = draft_of(out)
    assert (d["writer"], d["subject"], d["cc"]) == ("user", "iPhone 18 Pro India price", ["boss@x.com"])
    assert d["body"] == USER_TEXT + "\n"  # verbatim: no greeting, signature or sources added
    assert d["body"].count("Best regards") == 1 and "Prepared by" not in d["body"]
    assert "Rs 1,64,900" in d["html"] and '<a href="https://example.com/a"' in d["html"]
    assert fake.prompts == []


def test_without_text_or_earlier_steps_the_reason_says_what_is_missing():
    _, _, out = run({"to": ["rijin@gmail.com"]}, inputs={})
    assert out["result"]["status"] == "failed"
    assert "params.body" in out["result"]["summary"] and "depends_on" in out["result"]["summary"]
