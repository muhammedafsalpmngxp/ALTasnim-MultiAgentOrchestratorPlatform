import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { OrchestratorService, StatusBadge, ThreadStatus, ThreadSummary } from '@altasnim/shared';

type Filter = 'all' | ThreadStatus;

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'busy', label: 'Running' },
  { id: 'interrupted', label: 'Waiting' },
  { id: 'idle', label: 'Done' },
  { id: 'error', label: 'Failed' },
];

/** Every request the supervisor handled (LangGraph threads), searchable and filterable by status. */
@Component({
  selector: 'alt-runs-list',
  imports: [StatusBadge, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>Runs</h1>
          <p>Every request the supervisor handled: its agents, status and result. Open one for its full flow.</p>
        </div>
        <button class="btn" (click)="load()" [disabled]="loading()">{{ loading() ? 'Loading…' : 'Refresh' }}</button>
      </div>

      @if (error(); as err) {
        <div class="card error">{{ err }}</div>
      }

      <div class="card flush">
        <div class="toolbar">
          <input class="input search" type="search" placeholder="Search requests" aria-label="Search requests"
                 [value]="query()" (input)="query.set($any($event.target).value)" />
          <div class="segments" role="tablist" aria-label="Filter by status">
            @for (f of filters; track f.id) {
              <button type="button" role="tab" [attr.aria-selected]="filter() === f.id" [class.on]="filter() === f.id"
                      (click)="filter.set(f.id)">
                {{ f.label }}<span class="n">{{ count(f.id) }}</span>
              </button>
            }
          </div>
        </div>

        <div class="scroll">
          <table class="table">
            <thead>
              <tr><th>Request</th><th>Agents</th><th>Status</th><th class="right">Updated</th></tr>
            </thead>
            <tbody>
              @for (t of shown(); track t.threadId) {
                <tr class="clickable" (click)="open(t)">
                  <td>
                    <div class="req">{{ t.values.request || '(no request)' }}</div>
                    <div class="faint mono">{{ t.threadId.slice(0, 8) }}</div>
                  </td>
                  <td>
                    <div class="chips">
                      @for (a of agents(t); track a) {
                        <span class="chip">{{ a }}</span>
                      } @empty {
                        <span class="faint">—</span>
                      }
                    </div>
                  </td>
                  <td><alt-status-badge [status]="t.status" /></td>
                  <td class="right muted" [title]="t.updatedAt | date: 'medium'">{{ t.updatedAt | date: 'MMM d, HH:mm' }}</td>
                </tr>
              } @empty {
                <tr>
                  <td colspan="4" class="empty">
                    @if (loading()) {
                      Loading runs…
                    } @else if (threads().length) {
                      No run matches the search or filter.
                    } @else {
                      No runs yet. Ask a question in the Assistant (top right) to start one.
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `,
  styles: `
    .error { border-color: var(--danger); color: var(--danger); background: var(--danger-soft); margin-bottom: 14px; }
    .flush { padding: 0; overflow: hidden; }
    .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 14px 16px; border-bottom: 1px solid var(--border); }
    .search { flex: 1 1 260px; max-width: 420px; }
    .segments { display: inline-flex; flex-wrap: wrap; gap: 2px; padding: 3px; background: var(--surface-2); border-radius: 9px; }
    .segments button {
      display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 11px; font: inherit; font-size: 12.5px;
      font-weight: 500; color: var(--text-muted); background: none; border: 0; border-radius: 7px; cursor: pointer;
    }
    .segments button.on { color: var(--text); background: var(--surface); box-shadow: var(--shadow-sm); }
    .n { min-width: 18px; padding: 0 5px; font-size: 11px; border-radius: 999px; background: var(--surface-3); text-align: center; }
    .scroll { overflow-x: auto; }
    .table { min-width: 640px; }
    .table th, .table td { padding-left: 16px; padding-right: 16px; }
    .table th { border-radius: 0 !important; }
    .right { text-align: right; white-space: nowrap; }
    .req { font-weight: 500; overflow-wrap: anywhere; }
    .mono { font-family: var(--mono); font-size: 11.5px; }
    .chips { display: flex; flex-wrap: wrap; gap: 4px; }
    .chip { padding: 1px 8px; font-size: 12px; border-radius: 6px; color: var(--text-muted); background: var(--surface-2); border: 1px solid var(--border); }
    .empty { padding: 36px 16px !important; text-align: center; color: var(--text-muted); }
  `,
})
export class RunsList {
  private readonly orchestrator = inject(OrchestratorService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  protected readonly threads = signal<ThreadSummary[]>([]);
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly query = signal('');
  protected readonly filter = signal<Filter>('all');
  protected readonly filters = FILTERS;

  protected readonly shown = computed(() => {
    const q = this.query().trim().toLowerCase();
    return this.threads().filter(
      (t) =>
        (this.filter() === 'all' || t.status === this.filter()) &&
        (!q || (t.values.request ?? '').toLowerCase().includes(q) || t.threadId.startsWith(q)),
    );
  });

  constructor() {
    this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      this.threads.set(await this.orchestrator.threads());
    } catch (err) {
      this.error.set(`Could not load runs: ${err instanceof Error ? err.message : err}`);
    } finally {
      this.loading.set(false);
    }
  }

  protected count(filter: Filter): number {
    return filter === 'all' ? this.threads().length : this.threads().filter((t) => t.status === filter).length;
  }

  protected agents(t: ThreadSummary): string[] {
    return [...new Set((t.values.plan?.steps ?? []).map((s) => s.agent))];
  }

  protected open(t: ThreadSummary): void {
    // relative to wherever the shell mounted this micro-frontend (e.g. /runs)
    this.router.navigate([t.threadId], { relativeTo: this.route });
  }
}
