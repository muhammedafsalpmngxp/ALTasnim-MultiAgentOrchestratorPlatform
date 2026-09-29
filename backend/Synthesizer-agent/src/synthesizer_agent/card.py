"""What this agent does, served at GET /card."""

CARD = {
    "name": "synthesizer",
    "version": "0.7.0",
    "description": "Reads the outputs of earlier agents and writes ONE clear final answer to the user's question.",
    "endpoint": "POST (or PUT/PATCH) on any path, e.g. /synthesize",
    "input": {"question": "the user's question", "inputs": "outputs of the earlier agents, any shape"},
    "output": {"status": "ok | failed", "summary": "the answer", "answer": "the answer", "sources": "URLs"},
    "owner": "team-synthesizer",
}
