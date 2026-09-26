import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { AgentCard, AgentCardView, JsonView, agentApiUrl } from '@altasnim/shared';

/** Team Comms' own page. Talks only to its own deployment's custom routes (/card, /custom/*). */
@Component({
  selector: 'alt-communication-page',
  imports: [AgentCardView, JsonView],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page stack">
      <div>
        <h1>Communication agent</h1>
        <p class="muted">Owned by team-comms · deployment :8202 · UI :4302</p>
      </div>
      @if (error(); as err) {
        <div class="card error">{{ err }}</div>
      }
      @if (card(); as c) {
        <alt-agent-card [card]="c" />
      }
      @if (templates(); as t) {
        <div class="card">
          <h2>Email templates</h2>
          <alt-json-view [value]="t" label="GET /custom/templates" [open]="true" />
        </div>
      }
    </div>
  `,
  styles: `.error { border-color: var(--danger); background: var(--danger-soft); color: var(--danger); }`,
})
export class CommunicationPage {
  private readonly api = agentApiUrl('communication');
  protected readonly card = signal<AgentCard | null>(null);
  protected readonly templates = signal<unknown>(null);
  protected readonly error = signal<string | null>(null);

  constructor() {
    Promise.all([fetch(`${this.api}/card`), fetch(`${this.api}/custom/templates`)])
      .then(async ([card, templates]) => {
        if (!card.ok) throw new Error(`card: HTTP ${card.status}`);
        this.card.set(await card.json());
        this.templates.set(templates.ok ? await templates.json() : null);
      })
      .catch((err) => this.error.set(`Communication agent not reachable (:8202): ${err.message ?? err}`));
  }
}
