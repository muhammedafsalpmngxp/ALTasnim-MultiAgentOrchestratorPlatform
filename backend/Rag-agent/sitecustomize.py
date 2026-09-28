"""
Auto-imported by Python at interpreter startup for any module on `sys.path` named
`sitecustomize` — this is a standard CPython hook, not something wired in manually. Since
PYTHONPATH=/app/backend (set in Dockerfile.lt) puts backend/ on that path for BOTH the `backend`
(uvicorn) and `task_executor` processes, this installs the RAG pipeline/model-call log highlight
handler (see api/core/rag_log_formatter.py) for both — including task_executor, which runs
embedding/rerank calls during document parsing but never imports api/main.py.

Purely additive and silent on failure: never affects startup even if something is missing.
"""
try:
    from api.core.rag_log_formatter import install as _install_rag_log_highlights
    from api.core.rag_log_formatter import install_delayed as _install_rag_log_highlights_delayed

    _install_rag_log_highlights()
    # task_executor does its own logging setup shortly after this runs, which resets the root
    # logger's handlers and wipes the one just installed above — re-attach it once that's done.
    _install_rag_log_highlights_delayed()
except Exception:
    pass
