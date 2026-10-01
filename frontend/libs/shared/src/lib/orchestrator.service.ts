import { Injectable, inject } from '@angular/core';
import { Client, type Thread } from '@langchain/langgraph-sdk';

import { ORCHESTRATOR_API, ORCHESTRATOR_ASSISTANT } from './config';
import {
  AgentAdmin,
  AgentAdminAction,
  AgentCard,
  AuditEntry,
  OrchestratorValues,
  PlatformAdmin,
  PlatformPolicies,
  PlanningText,
  ThreadStatus,
  ThreadSummary,
} from './models';
import { RunSession, firstInterrupt } from './run-session';

/** The supervisor's error: FastAPI's detail, a 422's list as "field: message; …", else the status. */
async function failure(res: Response, what: string): Promise<Error> {
  const body = await res.json().catch(() => null);
  const detail = Array.isArray(body?.detail)
    ? body.detail.map((d: { loc?: (string | number)[]; msg?: string }) => `${d.loc?.slice(1).join('.') || 'body'}: ${d.msg}`).join('; ')
    : body?.detail;
  return new Error(detail || `${what} failed: ${res.status}`);
}

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

  /** Every agent with its port, graph, machine, status and card (custom route /platform/admin/agents). */
  async adminAgents(): Promise<PlatformAdmin> {
    const res = await fetch(`${this.apiUrl}/platform/admin/agents`);
    if (!res.ok) throw new Error(`GET /platform/admin/agents failed: ${res.status}`);
    return res.json();
  }

  /** Change the policies now (validated by the supervisor; the error says which value is out of range). */
  async updatePolicies(policies: PlatformPolicies): Promise<PlatformPolicies> {
    const res = await fetch(`${this.apiUrl}/platform/admin/policies`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(policies),
    });
    if (!res.ok) throw await failure(res, 'PUT /platform/admin/policies');
    return res.json();
  }

  /** Back to config/policies.yaml. */
  async resetPolicies(): Promise<PlatformPolicies> {
    const res = await fetch(`${this.apiUrl}/platform/admin/policies/reset`, { method: 'POST' });
    if (!res.ok) throw new Error(`POST /platform/admin/policies/reset failed: ${res.status}`);
    return res.json();
  }

  /** Every admin action of the supervisor's lifetime, newest first. */
  async adminAudit(): Promise<AuditEntry[]> {
    const res = await fetch(`${this.apiUrl}/platform/admin/audit`);
    if (!res.ok) throw new Error(`GET /platform/admin/audit failed: ${res.status}`);
    return res.json();
  }

  /** recheck (search the network again) | pause (leave out of planning) | resume. Returns the agent's new status. */
  async adminAction(agent: string, action: AgentAdminAction): Promise<AgentAdmin> {
    const res = await fetch(`${this.apiUrl}/platform/admin/agents/${encodeURIComponent(agent)}/${action}`, { method: 'POST' });
    if (!res.ok) throw await failure(res, `POST ${action}`);
    this.cardsCache = null; // paused / resumed agents change what the flow diagram shows
    return res.json();
  }

  /** Customise what the supervisor reads when it chooses this agent (a field left out is the agent's own). Saved
   *  on the supervisor's machine; used from the next question. ``null``: back to the agent's own card. */
  async customiseAgent(agent: string, text: Partial<PlanningText> | null): Promise<AgentAdmin> {
    const url = `${this.apiUrl}/platform/admin/agents/${encodeURIComponent(agent)}/planning`;
    const res = text
      ? await fetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(text) })
      : await fetch(url, { method: 'DELETE' });
    if (!res.ok) throw await failure(res, text ? 'Saving the planning text' : 'Resetting the planning text');
    this.cardsCache = null;
    return res.json();
  }
}
