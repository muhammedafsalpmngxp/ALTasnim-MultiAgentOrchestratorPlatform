import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { AgentCard, AgentCardView, JsonView, OrchestratorService } from '@altasnim/shared';

/** What the supervisor can plan with right now (healthy agents) and the policies plan_guard enforces. */
@Component({
  selector: 'alt-admin-page',
  imports: [AgentCardView, JsonView],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page stack">
      <div class="page-header">
        <div>
          <h1>Agents &amp; policies</h1>
          <p class="muted">Agents discovered by the orchestrator registry (GET /card on each deployment).</p>
        </div>
        <button class="btn btn-sm" (click)="load()">Refresh</button>
      </div>

      @if (error(); as err) {
        <div class="card error">{{ err }}</div>
      }

      <div class="grid">
        @for (card of cards(); track card.name) {
          <alt-agent-card [card]="card" />
        } @empty {
          <p class="muted">No healthy agents found. Start the agent deployments (ports 8201-8203).</p>
        }
      </div>

      @if (policies(); as p) {
        <div class="card">
          <h2>Policies</h2>
          <alt-json-view [value]="p" label="config/policies.yaml" [open]="true" />
        </div>
      }
    </div>
  `,
  styles: `
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
    .error { border-color: var(--danger); background: var(--danger-soft); color: var(--danger); }
  `,
})
export class AdminPage {
  private readonly orchestrator = inject(OrchestratorService);
  protected readonly cards = signal<AgentCard[]>([]);
  protected readonly policies = signal<Record<string, unknown> | null>(null);
  protected readonly error = signal<string | null>(null);

  constructor() {
    this.load();
  }

  protected async load(): Promise<void> {
    this.error.set(null);
    try {
      const [agents, policies] = await Promise.all([this.orchestrator.agents(), this.orchestrator.policies()]);
      this.cards.set(Object.values(agents));
      this.policies.set(policies);
    } catch (err) {
      this.error.set(`Could not load: ${err instanceof Error ? err.message : err}`);
    }
  }
}
