import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DecisionPanel, InterruptPayload, OrchestratorService, ThreadSummary } from '@altasnim/shared';

/** HITL inbox: every orchestrator thread waiting for a human (threads.search status=interrupted). */
@Component({
  selector: 'alt-approvals-inbox',
  imports: [DecisionPanel, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>Approvals</h1>
          <p class="muted">Runs waiting for a human decision or answer.</p>
        </div>
        <button class="btn btn-sm" (click)="load()" [disabled]="loading()">Refresh</button>
      </div>

      @if (notice(); as msg) {
        <div class="card notice">{{ msg }}</div>
      }
      @if (error(); as err) {
        <div class="card error">{{ err }}</div>
      }

      <div class="layout">
        <div class="card list">
          @for (item of items(); track item.threadId) {
            <button class="item" [class.active]="item.threadId === selectedId()" (click)="selectedId.set(item.threadId)">
              <div class="title">{{ title(item.interrupt) }}</div>
              <div class="muted small">{{ item.values.request }}</div>
              <div class="muted small">{{ item.updatedAt | date: 'short' }}</div>
            </button>
          } @empty {
            <p class="muted">{{ loading() ? 'Loading…' : 'Nothing is waiting for approval.' }}</p>
          }
        </div>

        <div class="detail">
          @if (selected(); as item) {
            @if (item.interrupt; as pending) {
              <alt-decision-panel [payload]="pending" [busy]="busy()" (decided)="decide(item, $event)" />
            }
          } @else if (items().length) {
            <p class="muted">Select an item.</p>
          }
        </div>
      </div>
    </div>
  `,
  styles: `
    .layout { display: grid; grid-template-columns: minmax(240px, 1fr) 2fr; gap: 14px; align-items: start; }
    .list { display: flex; flex-direction: column; gap: 6px; padding: 8px; }
    .item { text-align: left; font: inherit; color: inherit; background: none; border: 1px solid transparent;
            border-radius: var(--radius-sm); padding: 8px 10px; cursor: pointer; }
    .item:hover { background: var(--surface-2); }
    .item.active { border-color: var(--primary); background: var(--primary-soft); }
    .title { font-weight: 600; }
    .small { font-size: 12px; }
    .notice { border-color: var(--ok); background: var(--ok-soft); color: var(--ok); margin-bottom: 12px; }
    .error { border-color: var(--danger); background: var(--danger-soft); color: var(--danger); margin-bottom: 12px; }
    @media (max-width: 800px) { .layout { grid-template-columns: 1fr; } }
  `,
})
export class ApprovalsInbox {
  private readonly orchestrator = inject(OrchestratorService);
  protected readonly items = signal<ThreadSummary[]>([]);
  protected readonly selectedId = signal<string | null>(null);
  protected readonly loading = signal(false);
  protected readonly busy = signal(false);
  protected readonly notice = signal<string | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly selected = computed(() => this.items().find((i) => i.threadId === this.selectedId()) ?? null);

  constructor() {
    this.load();
  }

  protected title(p: InterruptPayload | null): string {
    if (!p) return 'Waiting';
    if (p.kind === 'clarification') return 'Question from the assistant';
    if (p.kind === 'agent_approval') return `Approve ${p.agent}: ${p.objective}`;
    return `Approve: ${p.objective}`;
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const items = await this.orchestrator.pendingApprovals();
      this.items.set(items);
      if (!items.some((i) => i.threadId === this.selectedId())) this.selectedId.set(items[0]?.threadId ?? null);
    } catch (err) {
      this.error.set(`Could not load approvals: ${err instanceof Error ? err.message : err}`);
    } finally {
      this.loading.set(false);
    }
  }

  protected async decide(item: ThreadSummary, decision: unknown): Promise<void> {
    this.busy.set(true);
    this.notice.set(null);
    try {
      const after = await this.orchestrator.resume(item.threadId, decision);
      const final = after.values.final ?? '';
      this.notice.set(
        after.interrupt
          ? 'Answer recorded. The run needs another decision.'
          : `Run completed: ${final.length > 160 ? final.slice(0, 160) + '…' : final}`,
      );
      await this.load();
    } catch (err) {
      this.error.set(`Could not resume: ${err instanceof Error ? err.message : err}`);
    } finally {
      this.busy.set(false);
    }
  }
}
