import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { OrchestratorService, StatusBadge, ThreadSummary } from '@altasnim/shared';

@Component({
  selector: 'alt-runs-list',
  imports: [StatusBadge, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>Runs</h1>
          <p class="muted">Every request handled by the orchestrator (LangGraph threads).</p>
        </div>
        <button class="btn btn-sm" (click)="load()" [disabled]="loading()">Refresh</button>
      </div>

      @if (error(); as err) {
        <div class="card error">{{ err }}</div>
      }

      <div class="card">
        <table class="table">
          <thead>
            <tr><th>Request</th><th>Agents</th><th>Status</th><th>Updated</th></tr>
          </thead>
          <tbody>
            @for (t of threads(); track t.threadId) {
              <tr class="clickable" (click)="open(t)">
                <td>{{ t.values.request || '(no request)' }}</td>
                <td class="muted">{{ agents(t) }}</td>
                <td><alt-status-badge [status]="t.status" /></td>
                <td class="muted">{{ t.updatedAt | date: 'short' }}</td>
              </tr>
            } @empty {
              <tr><td colspan="4" class="muted">{{ loading() ? 'Loading…' : 'No runs yet. Run one in Multi Agent Flow.' }}</td></tr>
            }
          </tbody>
        </table>
      </div>
    </div>
  `,
  styles: `.error { border-color: var(--danger); color: var(--danger); background: var(--danger-soft); margin-bottom: 12px; }`,
})
export class RunsList {
  private readonly orchestrator = inject(OrchestratorService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  protected readonly threads = signal<ThreadSummary[]>([]);
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);

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

  protected agents(t: ThreadSummary): string {
    const steps = t.values.plan?.steps ?? [];
    return [...new Set(steps.map((s) => s.agent))].join(', ') || '-';
  }

  protected open(t: ThreadSummary): void {
    // relative to wherever the shell mounted this micro-frontend (e.g. /runs)
    this.router.navigate([t.threadId], { relativeTo: this.route });
  }
}
