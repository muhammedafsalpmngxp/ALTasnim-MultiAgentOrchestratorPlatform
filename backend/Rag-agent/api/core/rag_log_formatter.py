"""
Adds Rich-colorized console highlights for RAG pipeline stage transitions, per-model
embedding/rerank/LLM token usage, and the actual user query being sent to the LLM.

This is purely additive: it never modifies or removes any existing log line. RAGFlow's own
`LLMBundle.*` and `[HISTORY]`/`[HISTORY STREAMLY]` logging calls live in vendored code
(backend/api/db/services/llm_service.py, backend/rag/llm/chat_model.py — see backend/README.md's
"DO NOT MODIFY" note) and are left untouched; this module just attaches an extra logging.Handler
to the root logger that recognizes those same messages (plus this app's own "[RAG]"
router/retrieval logs from api/routes/chat.py) and prints a short colored highlight line
alongside them.

IMPORTANT: any dynamic/arbitrary text (log message content, user queries, model names) is passed
through rich.markup.escape() before being interpolated into a markup string. Rich markup treats
"[" as the start of a style tag, so unescaped text containing "[" or "]" (e.g. actual chat
content, or a stray bracket in a filename) raises rich.errors.MarkupError — which, if caught
too broadly, silently discards the entire print (this is exactly what caused colored highlights
to not appear at all previously).
"""
import json
import logging
import re
import threading
import time

from rich.console import Console
from rich.markup import escape as _esc

# force_terminal=True: rich auto-disables ANSI color when stdout isn't an interactive TTY, which
# is exactly the case under Docker (logs are captured through a pipe, not a terminal) — so the
# highlights printed but appeared uncolored in `docker logs`. Forcing terminal mode emits the
# color codes regardless; `docker logs -f` and modern terminals render them. `soft_wrap=True`
# keeps long lines from being hard-wrapped mid-content.
_console = Console(force_terminal=True, soft_wrap=True)

_LLM_BUNDLE_RE = re.compile(r"LLMBundle\.(\w+) used_tokens: (\d+), llm_name: (.+)")

# call name -> (short label, color) — matches the method names in llm_service.py's LLMBundle
_STAGE_STYLES = {
    "encode": ("EMBED", "cyan"),
    "encode_queries": ("EMBED", "cyan"),
    "similarity": ("RERANK", "magenta"),
    "async_chat": ("LLM", "green"),
    "async_chat_streamly": ("LLM", "green"),
    "async_chat_streamly_delta": ("LLM", "green"),
    "describe": ("VISION", "yellow"),
    "describe_with_prompt": ("VISION", "yellow"),
    "transcription": ("ASR", "blue"),
    "stream_transcription": ("ASR", "blue"),
    "tts": ("TTS", "blue"),
}


def _tag(label: str, color: str) -> str:
    """A colored `[LABEL]` tag with BOTH brackets escaped so Rich never mis-parses it as markup."""
    return f"[bold {color}]\\[{_esc(label)}\\][/bold {color}]"


def _print_llm_bundle(call: str, tokens: str, model: str) -> None:
    label, color = _STAGE_STYLES.get(call, ("MODEL", "white"))
    _console.print(f"{_tag(label, color)} {_esc(model)}  [dim]tokens={_esc(tokens)}[/dim]")


def _print_rag_stage(label: str, color: str, detail: str) -> None:
    _console.print(f"{_tag(label, color)} {_esc(detail.strip())}")


def _print_user_query(history_json: str) -> None:
    """Extract and highlight just the last user message from a "[HISTORY]"/"[HISTORY STREAMLY]"
    JSON dump — the full dump (system prompt + all context) already prints via the normal
    handler; this only pulls out the one thing worth calling attention to in this raw form."""
    messages = json.loads(history_json)
    for msg in reversed(messages):
        if msg.get("role") == "user":
            _console.print(f"{_tag('USER QUERY', 'bright_white')} {_esc(str(msg.get('content', '')))}")
            return


class RichPipelineHighlightHandler(logging.Handler):
    """Prints a colored one-line highlight for RAG pipeline / model-call log records.

    Never raises and never suppresses the original record. Each recognized case is handled in
    its own try/except so a bad payload in one case (e.g. malformed JSON) can't hide a genuine
    bug in another.
    """

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()

        match = _LLM_BUNDLE_RE.search(msg)
        if match:
            try:
                self._safe(lambda: _print_llm_bundle(*match.groups()))
            finally:
                return

        if record.name == "lt_rag_pipeline":
            if msg.startswith("[RAG] router"):
                self._safe(lambda: _print_rag_stage("RAG · ROUTER", "yellow", msg[len("[RAG] router"):]))
                return
            if msg.startswith("[RAG] retrieval"):
                self._safe(lambda: _print_rag_stage("RAG · RETRIEVAL", "blue", msg[len("[RAG] retrieval"):]))
                return
            if msg.startswith("[RAG] agent"):
                # Analysis Agent step logs (api/agents/analysis_agent.py) — think/act/observe loop.
                self._safe(lambda: _print_rag_stage("AGENT", "bright_green", msg[len("[RAG] agent"):]))
                return

        if record.name == "root":
            if msg.startswith("[HISTORY STREAMLY]"):
                self._safe(lambda: _print_user_query(msg[len("[HISTORY STREAMLY]"):]))
                return
            if msg.startswith("[HISTORY]"):
                self._safe(lambda: _print_user_query(msg[len("[HISTORY]"):]))
                return

    @staticmethod
    def _safe(fn) -> None:
        try:
            fn()
        except Exception:
            # A logging-enhancement failure must never affect the actual request. If highlights
            # ever silently stop appearing again, temporarily replace `pass` below with
            # `_console.print_exception()` to see why.
            pass


def install(*, _announce: bool = True) -> None:
    """Attach the highlight handler if it isn't already present.

    Idempotent by design: RAGFlow's own startup code (common.settings.init_settings() in the
    backend, and task_executor's own logging setup) resets the root logger's handlers as part of
    its own init — which runs AFTER this module's first install() call and wipes it out. Calling
    install() again anytime (e.g. via install_delayed() below) safely re-attaches it if a prior
    reset removed it, and is a harmless no-op if it's still present.
    """
    root = logging.getLogger()
    if any(isinstance(h, RichPipelineHighlightHandler) for h in root.handlers):
        return
    root.addHandler(RichPipelineHighlightHandler())
    if _announce:
        # Confirmation so `docker logs` makes it obvious the handler is actually attached in THIS
        # process (backend vs. task_executor) — helpful since a silent failure here previously
        # looked identical to "nothing happened".
        _console.print("[dim]rag_log_formatter: highlight handler installed[/dim]")


def install_delayed(delay_seconds: float = 8.0) -> None:
    """Re-run install() a few seconds after startup, once RAGFlow's own logging init (which
    resets root handlers) has almost certainly already run and finished. Runs in a daemon thread
    so it never blocks or delays the app's actual startup."""

    def _worker():
        time.sleep(delay_seconds)
        install()

    threading.Thread(target=_worker, daemon=True).start()
