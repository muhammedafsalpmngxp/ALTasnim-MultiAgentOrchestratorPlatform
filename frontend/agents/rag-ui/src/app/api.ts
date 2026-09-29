import { agentApiUrl } from '@altasnim/shared';

export interface RagDocument {
  document_id: string;
  document_name: string;
  chunks: number;
}

export interface RetrievedChunk {
  id: string;
  document_id: string;
  document_name: string;
  chunk_index: number;
  page: number | null;
  content: string;
  score: number;
}

/** What happened when {question, chunks} was POSTed to one NEXT_AGENTS endpoint (PORT/PATH). */
export interface NextAgentResult {
  endpoint: string;
  url: string | null;
  status?: number;
  response?: unknown;
  error?: string;
}

export interface RetrieveResponse {
  question: string;
  chunks: RetrievedChunk[];
  next_agents: NextAgentResult[];
}

/** One line of a /stream endpoint (backend main.py): the plan, then each step as it starts, progresses and ends. */
export interface StepEvent {
  plan?: string[];
  step?: string;
  state?: 'start' | 'progress' | 'done';
  detail?: string;
  progress?: [number, number];
  chunks?: RetrievedChunk[];
}

/** POSTs to a Rag agent /stream endpoint: calls onEvent for every step as it happens, resolves with the result. */
export async function stream<T>(path: string, init: RequestInit, onEvent: (event: StepEvent) => void): Promise<T> {
  const res = await fetch(`${agentApiUrl('rag')}${path}`, init);
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const lines = (buffer + value).split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines.filter((l) => l.trim())) {
      const event = JSON.parse(line);
      if (event.error) throw new Error(event.error.detail);
      if ('result' in event) return event.result as T;
      onEvent(event as StepEvent);
    }
  }
  throw new Error('The Rag agent stopped before finishing');
}

/** Calls the Rag agent (:8000, proxied at /api/agents/rag). Throws with the API's error detail. */
export async function request<T = void>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${agentApiUrl('rag')}${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
