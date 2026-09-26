import { signal } from '@angular/core';
import type { Client, Thread } from '@langchain/langgraph-sdk';

import { InterruptPayload, OrchestratorValues, RunEvent } from './models';

export type SessionStatus = 'idle' | 'running' | 'interrupted' | 'done' | 'error';

export function firstInterrupt(thread: Thread): InterruptPayload | null {
  const groups = (thread.interrupts ?? {}) as Record<string, { value?: unknown }[]>;
  for (const items of Object.values(groups)) {
    for (const item of items ?? []) {
      if (item?.value) return item.value as InterruptPayload;
    }
  }
  return null;
}

/**
 * One conversation thread with the orchestrator, exposed as signals.
 * Uses the built-in Agent Server API: threads + runs.stream (values + custom events).
 */
export class RunSession {
  readonly threadId = signal<string | null>(null);
  readonly status = signal<SessionStatus>('idle');
  readonly values = signal<OrchestratorValues>({});
  readonly events = signal<RunEvent[]>([]);
  readonly interrupt = signal<InterruptPayload | null>(null);
  readonly error = signal<string | null>(null);

  constructor(
    private readonly client: Client,
    private readonly assistantId: string,
  ) {}

  /** Ask a new question (a new turn on the same thread). */
  async ask(request: string): Promise<void> {
    if (!this.threadId()) {
      const thread = await this.client.threads.create();
      this.threadId.set(thread.thread_id);
    }
    this.events.set([]);
    await this.run({ input: { request } });
  }

  /** Answer the current interrupt (approval decision or clarification answer). */
  async resume(value: unknown): Promise<void> {
    await this.run({ command: { resume: value } });
  }

  private async run(payload: { input?: Record<string, unknown>; command?: { resume: unknown } }): Promise<void> {
    const threadId = this.threadId();
    if (!threadId) return;
    this.status.set('running');
    this.interrupt.set(null);
    this.error.set(null);
    try {
      const stream = this.client.runs.stream(threadId, this.assistantId, {
        ...payload,
        streamMode: ['values', 'custom'],
      });
      for await (const chunk of stream as AsyncIterable<{ event: string; data: unknown }>) {
        if (chunk.event === 'values') {
          this.values.set(chunk.data as OrchestratorValues);
        } else if (chunk.event === 'custom') {
          this.events.update((list) => [...list, chunk.data as RunEvent]);
        } else if (chunk.event === 'error') {
          throw new Error(typeof chunk.data === 'string' ? chunk.data : JSON.stringify(chunk.data));
        }
      }
      const thread = await this.client.threads.get(threadId);
      this.values.set((thread.values ?? this.values()) as OrchestratorValues);
      const pending = firstInterrupt(thread);
      this.interrupt.set(pending);
      this.status.set(pending ? 'interrupted' : 'done');
    } catch (err) {
      this.error.set(err instanceof Error ? err.message : String(err));
      this.status.set('error');
    }
  }
}
