import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, effect, inject, signal } from '@angular/core';

import { formatSeconds } from './web-search/format';
import { SearchConsole } from './web-search/search-console/search-console';
import { WebSearchApi } from './web-search/web-search-api';
import { HistoryEntry } from './web-search/web-search.models';

type Theme = 'light' | 'dark';
const THEME_KEY = 'altasnim.web-search.theme';

/** Saved choice, else the system preference. */
function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') {
      return saved;
    }
  } catch {
    // storage blocked (private window): fall back to the system preference
  }
  return typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/**
 * Team Search's own page. Talks only to its own deployment's custom routes (/card, /custom/*).
 * The light/dark theme is scoped to this page (tokens redefined on the host), so the shell and other agents' pages
 * are not affected.
 */
@Component({
  selector: 'alt-web-search-page',
  imports: [DatePipe, SearchConsole],
  providers: [WebSearchApi],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[attr.data-theme]': 'theme()' },
  template: `
    <div class="page stack">
      <header class="page-head">
        <div class="page-head__title">
          <span class="page-head__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
            </svg>
          </span>
          <div>
            <h1>Web search agent</h1>
            <p class="muted page-head__sub">
              Owned by team-search · deployment :8201 · UI :4301 · in a plan it runs after the supervisor and its
              result goes to the verifier
            </p>
          </div>
        </div>
        <div class="page-head__actions">
          @if (online() !== null) {
            <span class="conn" [class.conn--up]="online()" role="status">
              <span class="conn__dot"></span>{{ online() ? 'Connected' : 'Offline' }} · :8201
            </span>
          }
          <button class="btn theme-toggle" type="button" (click)="toggleTheme()"
                [attr.aria-label]="theme() === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'"
                [title]="theme() === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'">
          @if (theme() === 'dark') {
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
            </svg>
            <span>Light</span>
          } @else {
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
            </svg>
            <span>Dark</span>
          }
          </button>
        </div>
      </header>

      @if (error(); as err) {
        <div class="card error" role="alert">{{ err }}</div>
      }

      <section class="card stack">
        <div class="section-head">
          <div>
            <h2>Try the agent</h2>
            <p class="muted section-head__sub">Runs one live search on this deployment and draws the flow step by step.</p>
          </div>
        </div>
        <alt-ws-search-console (searched)="loadHistory()" />
      </section>

      <section class="card stack">
        <div class="section-head">
          <div>
            <h2>Recent runs</h2>
            <p class="muted section-head__sub">{{ history().length }} saved run(s) on this deployment</p>
          </div>
          <button class="btn btn-sm" type="button" (click)="loadHistory()">Refresh</button>
        </div>
        @if (history().length) {
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr><th>When</th><th>Query</th><th>From</th><th>Status</th><th class="num">Sources</th><th class="num">Time</th><th></th></tr>
              </thead>
              <tbody>
                @for (run of history(); track run.trace_id) {
                  <tr>
                    <td class="muted nowrap">{{ run.created_at | date: 'short' }}</td>
                    <td class="query">{{ run.query }}<div class="muted preview">{{ run.preview }}</div></td>
                    <td class="muted nowrap">{{ run.source_agent ?? '–' }}</td>
                    <td>
                      <span class="chip" [class.chip--ok]="run.status === 'ok'" [class.chip--failed]="run.status !== 'ok'">
                        {{ run.status }}
                      </span>
                    </td>
                    <td class="num">{{ run.sources }}</td>
                    <td class="muted num nowrap">{{ formatSeconds(run.total_s) }}</td>
                    <td class="actions">
                      <button class="btn btn-sm" type="button" [disabled]="retrying() === run.trace_id"
                              (click)="retry(run.trace_id)" title="Send another request to the output agents - no search, no LLM">
                        {{ retrying() === run.trace_id ? 'Retrying…' : 'Retry' }}
                      </button>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        } @else {
          <p class="empty muted">No runs yet on this deployment.</p>
        }
      </section>
    </div>
  `,
  styles: `
    /* Same tokens as libs/shared/styles/theme.css, redefined here so the toggle wins over the system preference. */
    :host {
      display: block;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
    }
    :host([data-theme='light']) {
      --bg: #f5f7fb;
      --surface: #ffffff;
      --surface-2: #f1f3f6;
      --border: #e3e6eb;
      --text: #1c2330;
      --text-muted: #5e6878;
      --primary: #3d5bd9;
      --primary-soft: #e8edfd;
      --info: #2f5fd0;
      --info-soft: #e7eefc;
      --ok: #1f7a3f;
      --ok-soft: #e4f4e9;
      --warn: #9a6200;
      --warn-soft: #fbf1dc;
      --danger: #b3261e;
      --danger-soft: #fbe7e5;
      --flow-band-a: #eef2fd;
      --flow-band-b: #e2e8fb;
      --flow-edge: #5b7cf0;
      --flow-edge-idle: #b9c5ee;
      --shadow: 0 1px 2px rgba(16, 24, 40, 0.06), 0 1px 3px rgba(16, 24, 40, 0.08);
      color-scheme: light;
    }
    :host([data-theme='dark']) {
      --bg: #0f1318;
      --surface: #161b22;
      --surface-2: #1d232c;
      --border: #2b323d;
      --text: #e6e9ee;
      --text-muted: #9aa4b2;
      --primary: #8ea4ff;
      --primary-soft: #1c2442;
      --info: #7ea2ff;
      --info-soft: #1a2440;
      --ok: #5cc587;
      --ok-soft: #15301f;
      --warn: #e0b04f;
      --warn-soft: #33280f;
      --danger: #f08a82;
      --danger-soft: #3a1917;
      --flow-band-a: #151b2c;
      --flow-band-b: #1a2237;
      --flow-edge: #7f9bff;
      --flow-edge-idle: #39456a;
      --shadow: 0 1px 2px rgba(0, 0, 0, 0.4), 0 1px 3px rgba(0, 0, 0, 0.3);
      color-scheme: dark;
    }

    .page { gap: 16px; }

    .page-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; padding-bottom: 4px; }
    .page-head__title { display: flex; gap: 12px; align-items: flex-start; min-width: 0; }
    .page-head__icon {
      flex: none; display: grid; place-items: center; width: 40px; height: 40px;
      border-radius: var(--radius); background: var(--primary-soft); color: var(--primary);
    }
    .page-head h1 { margin: 0 0 2px; font-size: 22px; font-weight: 700; }
    .page-head__sub { margin: 0; font-size: 13px; }

    .page-head__actions { flex: none; display: flex; align-items: center; gap: 10px; }
    .conn {
      display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px;
      font-size: 12px; font-weight: 600; background: var(--danger-soft); color: var(--danger);
    }
    .conn--up { background: var(--ok-soft); color: var(--ok); }
    .conn__dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
    .theme-toggle { flex: none; display: inline-flex; align-items: center; gap: 6px; }
    .theme-toggle:focus-visible, .btn:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }

    .section-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
    .section-head h2 { margin: 0; }
    .section-head__sub { margin: 2px 0 0; font-size: 12px; }

    .error { border-color: var(--danger); background: var(--danger-soft); color: var(--danger); }

    .table-wrap { overflow-x: auto; margin: 0 -16px -16px; }
    .table-wrap .table th:first-child, .table-wrap .table td:first-child { padding-left: 16px; }
    .table-wrap .table th:last-child, .table-wrap .table td:last-child { padding-right: 16px; }
    .table th { background: var(--surface-2); text-transform: uppercase; letter-spacing: 0.04em; font-size: 11px; }
    .table tbody tr:hover td { background: var(--surface-2); }
    .table tbody tr:last-child td { border-bottom: 0; }
    .query { min-width: 220px; font-weight: 500; }
    .preview { font-size: 12px; font-weight: 400; margin-top: 2px; }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .nowrap { white-space: nowrap; }
    .actions { text-align: right; }

    .chip { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
    .chip--ok { background: var(--ok-soft); color: var(--ok); }
    .chip--failed { background: var(--danger-soft); color: var(--danger); }

    .empty { margin: 0; padding: 24px; text-align: center; border: 1px dashed var(--border); border-radius: var(--radius-sm); }

    @media (max-width: 640px) {
      .page { padding: 16px; }
      .page-head { flex-direction: column; }
    }
  `,
})
export class WebSearchPage {
  private readonly api = inject(WebSearchApi);
  /** null until the deployment answered (or not). */
  protected readonly online = signal<boolean | null>(null);
  protected readonly history = signal<HistoryEntry[]>([]);
  protected readonly error = signal<string | null>(null);
  protected readonly retrying = signal<string | null>(null);
  protected readonly theme = signal<Theme>(initialTheme());
  protected readonly formatSeconds = formatSeconds;

  constructor() {
    effect(() => {
      try {
        localStorage.setItem(THEME_KEY, this.theme());
      } catch {
        // storage blocked: the choice lasts for this visit only
      }
    });
    this.api.card().subscribe({
      next: () => this.online.set(true),
      error: (err) => {
        this.online.set(false);
        this.error.set(`Web search agent not reachable (:8201): ${err.message ?? err}`);
      },
    });
    this.loadHistory();
  }

  protected toggleTheme(): void {
    this.theme.update((t) => (t === 'dark' ? 'light' : 'dark'));
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
