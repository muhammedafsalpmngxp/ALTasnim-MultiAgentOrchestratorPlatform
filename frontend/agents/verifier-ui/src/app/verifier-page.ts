import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { AgentCard, AgentCardView, agentApiUrl } from '@altasnim/shared';

/** Team Quality's own page. */
@Component({
  selector: 'alt-verifier-page',
  imports: [AgentCardView],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page stack">
      <div>
        <h1>Verifier agent</h1>
        <p class="muted">Owned by team-quality · deployment :8203 · UI :4303</p>
      </div>
      @if (error(); as err) {
        <div class="card error">{{ err }}</div>
      }
      @if (card(); as c) {
        <alt-agent-card [card]="c" />
      }
      <div class="card">
        <h2>When it runs</h2>
        <p class="muted">
          Added automatically by the orchestrator's policy: before any human approval, and at the end of plans
          without a verifier. A failed verification makes the supervisor replan.
        </p>
      </div>
    </div>
  `,
  styles: `.error { border-color: var(--danger); background: var(--danger-soft); color: var(--danger); }`,
})
export class VerifierPage {
  protected readonly card = signal<AgentCard | null>(null);
  protected readonly error = signal<string | null>(null);

  constructor() {
    fetch(`${agentApiUrl('verifier')}/card`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        this.card.set(await res.json());
      })
      .catch((err) => this.error.set(`Verifier agent not reachable (:8203): ${err.message ?? err}`));
  }
}
