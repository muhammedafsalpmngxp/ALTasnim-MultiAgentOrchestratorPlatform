import { Injectable } from '@angular/core';
import { agentApiUrl } from '@altasnim/shared';

import { AgentCard, Run } from './synthesizer.models';

/** Port the agent listens on (SYNTHESIZER_PORT in backend/.env). Keep in sync with proxy.conf.json. */
const AGENT_PORT = 8204;

/**
 * Talks to the Synthesizer agent through the team proxy: /api/agents/synthesizer -> :8204
 * (dev: proxy.conf.json, prod: API gateway). Same origin, so no CORS is needed.
 *
 * Uses fetch instead of HttpClient on purpose: a remote cannot count on the shell's providers.
 */
@Injectable({ providedIn: 'root' })
export class SynthesizerService {
  private readonly base = agentApiUrl('synthesizer');

  /** Where other agents send their data (shown on the page), e.g. http://192.168.1.33:8204 */
  async apiUrl(): Promise<string> {
    return `${location.protocol}//${location.hostname}:${AGENT_PORT}`;
  }

  async card(): Promise<AgentCard | null> {
    try {
      const res = await fetch(`${this.base}/card`, { signal: AbortSignal.timeout(5000) });
      return res.ok ? await res.json() : null;
    } catch {
      return null;
    }
  }

  /** Requests the agent received, newest first. Throws if the agent is unreachable. */
  async runs(): Promise<Run[]> {
    const res = await fetch(`${this.base}/runs`, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) throw new Error(`GET /runs failed with status ${res.status}`);
    return res.json();
  }

  /** One request, including the prompt sent to the LLM. */
  async run(id: string): Promise<Run | null> {
    const res = await fetch(`${this.base}/runs/${id}`, { signal: AbortSignal.timeout(5000) });
    return res.ok ? res.json() : null;
  }

  async clearRuns(): Promise<void> {
    await fetch(`${this.base}/runs`, { method: 'DELETE', signal: AbortSignal.timeout(5000) });
  }
}
