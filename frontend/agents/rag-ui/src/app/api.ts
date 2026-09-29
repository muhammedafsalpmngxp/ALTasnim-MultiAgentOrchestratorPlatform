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
