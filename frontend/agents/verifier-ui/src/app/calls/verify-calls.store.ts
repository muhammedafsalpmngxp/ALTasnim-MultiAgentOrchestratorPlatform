import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { agentApiUrl } from '@altasnim/shared';

import { VerifyCall, verdictOf } from './verify-call';

export type VerdictFilter = 'all' | 'passed' | 'failed';

const POLL_MS = 3000;

/** Live list of calls to POST /verify, polled from the verifier. Provided per page, stops polling on destroy. */
@Injectable()
export class VerifyCallsStore {
  private readonly base = `${agentApiUrl('verifier')}/verify/calls`;

  readonly calls = signal<VerifyCall[]>([]);
  readonly connected = signal<boolean | null>(null);
  readonly now = signal(Date.now());
  readonly query = signal('');
  readonly filter = signal<VerdictFilter>('all');

  /** null = follow the newest call. */
  private readonly pinnedId = signal<string | null>(null);

  readonly filtered = computed(() => {
    const q = this.query().trim().toLowerCase();
    const f = this.filter();
    return this.calls().filter((c) => {
      const v = verdictOf(c);
      if (f === 'passed' && v !== 'passed') return false;
      if (f === 'failed' && v !== 'failed' && v !== 'error') return false;
      return !q || `${c.question} ${c.task?.task_id ?? ''} ${c.client}`.toLowerCase().includes(q);
    });
  });

  readonly selected = computed<VerifyCall | null>(() => {
    const calls = this.calls();
    const id = this.pinnedId();
    return (id && calls.find((c) => c.id === id)) || this.filtered().at(0) || null;
  });

  /** A newer call arrived while the user is looking at an older one. */
  readonly hasNewer = computed(() => {
    const sel = this.selected();
    const newest = this.filtered()[0];
    return !!this.pinnedId() && !!sel && !!newest && newest.id !== sel.id;
  });

  readonly stats = computed(() => {
    const calls = this.calls();
    const done = calls.filter((c) => c.result);
    const passed = done.filter((c) => c.result!.passed).length;
    const timed = calls.filter((c) => typeof c.duration_ms === 'number');
    return {
      total: calls.length,
      passed,
      failed: calls.filter((c) => ['failed', 'error'].includes(verdictOf(c))).length,
      passRate: done.length ? Math.round((passed / done.length) * 100) : null,
      avgMs: timed.length ? Math.round(timed.reduce((s, c) => s + c.duration_ms!, 0) / timed.length) : null,
      sources: calls.reduce(
        (n, c) => n + Object.values(c.task?.inputs ?? {}).reduce<number>(
          (m, o) => m + (Array.isArray((o as { sources?: unknown[] })?.sources) ? (o as { sources: unknown[] }).sources.length : 0), 0),
        0,
      ),
    };
  });

  constructor() {
    this.refresh();
    const timer = setInterval(() => this.refresh(), POLL_MS);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  select(id: string): void {
    this.pinnedId.set(id === this.filtered()[0]?.id ? null : id);
  }

  followLatest(): void {
    this.pinnedId.set(null);
  }

  async refresh(): Promise<void> {
    try {
      const res = await fetch(this.base, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const calls = (await res.json()) as VerifyCall[];
      this.calls.set(calls);
      this.connected.set(true);
    } catch {
      this.connected.set(false);
    } finally {
      this.now.set(Date.now());
    }
  }

  async clear(): Promise<void> {
    await fetch(this.base, { method: 'DELETE' });
    this.pinnedId.set(null);
    await this.refresh();
  }
}
