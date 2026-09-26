import { Injectable, inject } from '@angular/core';
import { Client, type Thread } from '@langchain/langgraph-sdk';

import { ORCHESTRATOR_API, ORCHESTRATOR_ASSISTANT } from './config';
import { AgentCard, OrchestratorValues, ThreadStatus, ThreadSummary } from './models';
import { RunSession, firstInterrupt } from './run-session';

function toSummary(thread: Thread): ThreadSummary {
  return {
    threadId: thread.thread_id,
    status: thread.status as ThreadStatus,
    createdAt: thread.created_at,
    updatedAt: thread.updated_at,
    values: (thread.values ?? {}) as OrchestratorValues,
    interrupt: firstInterrupt(thread),
  };
}

/** Everything the UI does with the orchestrator, through @langchain/langgraph-sdk. */
@Injectable({ providedIn: 'root' })
export class OrchestratorService {
  private readonly apiUrl = inject(ORCHESTRATOR_API);
  readonly client = new Client({ apiUrl: this.apiUrl });

  /** A new flow (conversation thread). */
  newSession(): RunSession {
    return new RunSession(this.client, ORCHESTRATOR_ASSISTANT);
  }

  /** Recent runs (threads), newest first. */
  async threads(limit = 50): Promise<ThreadSummary[]> {
    const threads = await this.client.threads.search({ limit, sortBy: 'updated_at', sortOrder: 'desc' });
    return threads.map(toSummary);
  }

  /** Approvals inbox: every thread waiting for a human. */
  async pendingApprovals(): Promise<ThreadSummary[]> {
    const threads = await this.client.threads.search({
      status: 'interrupted',
      limit: 100,
      sortBy: 'updated_at',
      sortOrder: 'desc',
    });
    return threads.map(toSummary);
  }

  async thread(threadId: string): Promise<ThreadSummary> {
    return toSummary(await this.client.threads.get(threadId));
  }

  /** Answer an interrupt on any thread (used by the Approvals inbox) and wait for the run to settle. */
  async resume(threadId: string, value: unknown): Promise<ThreadSummary> {
    await this.client.runs.wait(threadId, ORCHESTRATOR_ASSISTANT, { command: { resume: value } });
    return this.thread(threadId);
  }

  private cardsCache: { at: number; value: Promise<Record<string, AgentCard>> } | null = null;

  /** Agent cards, cached for 30s (used by the flow diagram on every page). Never throws. */
  agentCards(): Promise<Record<string, AgentCard>> {
    if (!this.cardsCache || Date.now() - this.cardsCache.at > 30_000) {
      const value = this.agents().catch(() => {
        this.cardsCache = null;
        return {};
      });
      this.cardsCache = { at: Date.now(), value };
    }
    return this.cardsCache.value;
  }

  /** Agents the supervisor can currently plan with (custom route /platform/agents). */
  async agents(): Promise<Record<string, AgentCard>> {
    const res = await fetch(`${this.apiUrl}/platform/agents`);
    if (!res.ok) throw new Error(`GET /platform/agents failed: ${res.status}`);
    return res.json();
  }

  async policies(): Promise<Record<string, unknown>> {
    const res = await fetch(`${this.apiUrl}/platform/policies`);
    if (!res.ok) throw new Error(`GET /platform/policies failed: ${res.status}`);
    return res.json();
  }
}
