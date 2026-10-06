"""What this agent does, served at GET /card (the platform's AgentCard fields; this agent has its own build context,
so it is a plain dict rather than utils.contracts.AgentCard)."""

CARD = {
    "name": "synthesizer",
    "version": "0.8.0",
    "description": "Writes ONE clear final answer: from the outputs of earlier agents (their facts and sources), or "
                   "from a text the user gave (summarise, rewrite, explain or answer a question about it).",
    "when_to_use": "The last step of a question whose facts other steps found (depends_on them and their verifier), "
                   "with the user's question in params.question. Or alone, when the user gives the text to work on "
                   "(summarise, rewrite, translate the wording, answer from it): the text verbatim in params.content "
                   "and what to do with it in params.question.",
    "when_not_to_use": "Finding facts (use a source agent first); sending messages; when no step produces output and "
                       "the user gave no text to work on.",
    "examples": [
        "Write the final answer to: what is the retention money? (params: question='What is the retention money?'; "
        "depends_on the source and verifier steps)",
        "Summarise this text in 3 bullet points: <the user's text> (params: question='Summarise in 3 bullet "
        "points', content='<the user's text, verbatim>'; no other step)",
    ],
    "approval_mode": "none",
    "role": "final_answer",
    "side_effects": False,
    "params_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string",
                         "description": "the user's question, or what to do with the content (e.g. 'summarise')"},
            "content": {"type": "string", "x-content": True,
                        "description": "a text the user gave to work on, copied verbatim (only when the user gave it)"},
        },
        "required": ["question"],
    },
    "output_schema": {"type": "object", "properties": {
        "status": {"description": "ok | failed"},
        "summary": {"description": "the answer"},
        "answer": {"description": "the answer"},
        "sources": {"description": "the source URLs of the facts used"},
    }},
    "endpoint": "POST (or PUT/PATCH) on any path, e.g. /synthesize",
    "input": {"question": "the user's question", "inputs": "outputs of the earlier agents, any shape"},
    "output": {"status": "ok | failed", "summary": "the answer", "answer": "the answer", "sources": "URLs"},
    "owner": "team-synthesizer",
}
