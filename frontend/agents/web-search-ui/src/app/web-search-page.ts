import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { AgentCard, AgentCardView, JsonView, agentApiUrl } from '@altasnim/shared';

/** Team Search's own page. Talks only to its own deployment's custom routes (/card, /custom/*). */
@Component({
  selector: 'alt-web-search-page',
  imports: [AgentCardView, JsonView],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page stack">
      <div>
        <h1>Web search agent</h1>
        <p class="muted">Owned by team-search · deployment :8201 · UI :4301</p>
      </div>
      @if (error(); as err) {
        <div class="card error">{{ err }}</div>
      }
      @if (card(); as c) {
        <alt-agent-card [card]="c" />
      }
      @if (sources(); as s) {
        <div class="card">
          <h2>Search sources</h2>
          <alt-json-view [value]="s" label="GET /custom/sources" [open]="true" />
        </div>
      }
    </div>
  `,
  styles: `.error { border-color: var(--danger); background: var(--danger-soft); color: var(--danger); }`,
})
export class WebSearchPage {
  private readonly api = agentApiUrl('web_search');
  protected readonly card = signal<AgentCard | null>(null);
  protected readonly sources = signal<unknown>(null);
  protected readonly error = signal<string | null>(null);

  constructor() {
    Promise.all([fetch(`${this.api}/card`), fetch(`${this.api}/custom/sources`)])
      .then(async ([card, sources]) => {
        if (!card.ok) throw new Error(`card: HTTP ${card.status}`);
        this.card.set(await card.json());
        this.sources.set(sources.ok ? await sources.json() : null);
      })
      .catch((err) => this.error.set(`Web search agent not reachable (:8201): ${err.message ?? err}`));
  }
}
