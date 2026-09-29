import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { AgentCard, AgentCardView } from '@altasnim/shared';

import { formatSeconds } from './web-search/format';
import { SearchConsole } from './web-search/search-console/search-console';
import { WebSearchApi } from './web-search/web-search-api';
import { HistoryEntry } from './web-search/web-search.models';

/** Team Search's own page. Talks only to its own deployment's custom routes (/card, /custom/*). */
@Component({
  selector: 'alt-web-search-page',
  imports: [AgentCardView, DatePipe, SearchConsole],
  providers: [WebSearchApi],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page stack">
      <div>
        <h1>Web search agent</h1>
        <p class="muted">
          Owned by team-search · deployment :8201 · UI :4301 · in a plan it runs after the supervisor and its result
          goes to the verifier
        </p>
      </div>
      @if (error(); as err) {
        <div class="card error">{{ err }}</div>
      }

      <div class="card stack">
        <h2>Try the agent</h2>
        <alt-ws-search-console (searched)="loadHistory()" />
      </div>

      <div class="card">
        <div class="row between">
          <h2>Recent runs</h2>
          <button class="btn btn-sm" type="button" (click)="loadHistory()">Refresh</button>
        </div>
        @if (history().length) {
          <table class="table">
            <thead>
              <tr><th>When</th><th>Query</th><th>From</th><th>Status</th><th>Sources</th><th>Time</th><th></th></tr>
            </thead>
            <tbody>
              @for (run of history(); track run.trace_id) {
                <tr>
                  <td class="muted">{{ run.created_at | date: 'short' }}</td>
                  <td>{{ run.query }}<div class="muted preview">{{ run.preview }}</div></td>
                  <td class="muted">{{ run.source_agent }}</td>
                  <td>{{ run.status }}</td>
                  <td>{{ run.sources }}</td>
                  <td class="muted">{{ formatSeconds(run.total_s) }}</td>
                  <td>
                    <button class="btn btn-sm" type="button" [disabled]="retrying() === run.trace_id"
                            (click)="retry(run.trace_id)" title="Send another request to the output agents - no search, no LLM">
                      {{ retrying() === run.trace_id ? 'Retrying…' : 'Retry' }}
                    </button>
                  </td>
                </tr>
              }
            </tbody>
          </table>
        } @else {
          <p class="muted">No runs yet on this deployment.</p>
        }
      </div>

      @if (card(); as c) {
        <alt-agent-card [card]="c" />
      }
    </div>
  `,
  styles: `
    .error { border-color: var(--danger); background: var(--danger-soft); color: var(--danger); }
    .between { justify-content: space-between; }
    .preview { font-size: 12px; }
  `,
})
export class WebSearchPage {
  private readonly api = inject(WebSearchApi);
  protected readonly card = signal<AgentCard | null>(null);
  protected readonly history = signal<HistoryEntry[]>([]);
  protected readonly error = signal<string | null>(null);
  protected readonly retrying = signal<string | null>(null);
  protected readonly formatSeconds = formatSeconds;

  constructor() {
    this.api.card().subscribe({
      next: (card) => this.card.set(card),
      error: (err) => this.error.set(`Web search agent not reachable (:8201): ${err.message ?? err}`),
    });
    this.loadHistory();
  }

  /** Send another request to the output agents with the saved run - no search, no LLM. */
  protected retry(traceId: string): void {
    this.retrying.set(traceId);
    this.api.retry(traceId).subscribe({
      next: () => {
        this.retrying.set(null);
        this.loadHistory();
      },
      error: (err) => {
        this.retrying.set(null);
        this.error.set(`Retry failed: ${err.error?.detail ?? err.message ?? err}`);
      },
    });
  }

  protected loadHistory(): void {
    this.api.history().subscribe({ next: (runs) => this.history.set(runs), error: () => this.history.set([]) });
  }
}
