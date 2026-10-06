// Same shapes as backend/synthesizer_agent/src/synthesizer_agent/api.py and runs.py

/** A typical request. The agent accepts any JSON or text on any path. */
export interface SynthesizeRequest {
  question: string;
  inputs: Record<string, unknown>;
}

export interface SynthesizeResult {
  status: 'ok' | 'failed';
  summary: string;
  answer?: string;
  sources?: string[];
}

export interface LlmInfo {
  model: string;
  base_url: string;
}

/** One request the agent handled (GET /runs). `prompt` is only in GET /runs/{id}. */
export interface Run {
  id: string;
  state: 'running' | 'done' | 'error';
  received_at: string;
  finished_at?: string | null;
  seconds?: number | null;
  /** How it arrived, e.g. "POST /verify" */
  endpoint?: string;
  /** null when the sender gave no question (the LLM works it out from the data) */
  question: string | null;
  inputs: Record<string, unknown>;
  llm?: LlmInfo | null;
  prompt?: string | null;
  result?: SynthesizeResult | null;
  error?: string | null;
}

/** GET /card */
export interface AgentCard {
  name: string;
  version: string;
  description: string;
  llm?: LlmInfo | null;
}
