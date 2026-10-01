import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { AuditEntry } from '@altasnim/shared';

import { agoMs } from './admin-utils';

type Kind = 'all' | 'agent' | 'policies';

const TONE: Record<string, string> = {
  'agent.pause': 'warn',
  'agent.resume': 'ok',
  'agent.recheck': 'info',
  'agent.customise': 'info',
  'agent.reset_planning': 'warn',
  'policies.update': 'info',
  'policies.reset': 'warn',
};

/** Every admin action of the supervisor's lifetime (in memory, newest first): search, filter, CSV export. */
@Component({
  selector: 'alt-admin-audit',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="toolbar">
      <input class="input search" type="search" placeholder="Search actions, agents, details…" aria-label="Search the audit log"
             [value]="query()" (input)="query.set($any($event.target).value)" />
      <div class="chips" role="group" aria-label="Filter by kind">
        @for (k of kinds; track k.id) {
          <button class="chip" [class.on]="kind() === k.id" [attr.aria-pressed]="kind() === k.id" (click)="kind.set(k.id)">{{ k.label }}</button>
        }
      </div>
      <button class="btn btn-sm" [disabled]="!shown().length" (click)="exportCsv()">Export CSV</button>
    </div>

    <div class="card flush">
      @if (shown().length) {
        <div class="scroll">
          <table class="table">
            <thead><tr><th>When</th><th>Action</th><th>Target</th><th>Detail</th><th>By</th></tr></thead>
            <tbody>
              @for (e of shown(); track $index) {
                <tr>
                  <td class="nowrap" [title]="full(e.at)">{{ ago(e.at) }}<div class="faint small">{{ time(e.at) }}</div></td>
                  <td><span class="badge" [attr.data-tone]="tone(e.action)">{{ e.action }}</span></td>
                  <td class="mono nowrap">{{ e.target }}</td>
                  <td class="detail">
                    @for (part of parts(e.detail); track $index) { <div>{{ part }}</div> }
                  </td>
                  <td class="muted small">{{ e.by }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      } @else {
        <div class="empty">
          <strong>{{ entries().length ? 'Nothing matches' : 'No admin actions yet' }}</strong>
          <p class="muted">
            Pausing, resuming, re-checking and customising agents and every policy change is recorded here, kept in the supervisor's
            memory until it restarts (the latest 200).
          </p>
        </div>
      }
    </div>
    <p class="foot faint small">{{ shown().length }} of {{ entries().length }} entries</p>
  `,
  styles: `
    :host { display: block; }
    .small { font-size: 12px; } .mono { font-family: var(--mono); font-size: 12.5px; } .nowrap { white-space: nowrap; }
    .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 12px; }
    .search { flex: 1 1 240px; max-width: 360px; height: 34px; }
    .chips { display: flex; gap: 6px; }
    .chip { height: 30px; padding: 0 12px; font: inherit; font-size: 12.5px; color: var(--text-muted); background: var(--surface);
            border: 1px solid var(--border); border-radius: 999px; cursor: pointer; }
    .chip:hover { border-color: var(--border-strong); color: var(--text); }
    .chip.on { color: var(--primary); background: var(--primary-soft); border-color: transparent; font-weight: 500; }
    .toolbar .btn { margin-left: auto; }
    .flush { padding: 0; overflow: hidden; }
    .scroll { overflow-x: auto; }
    .card > .scroll > .table { margin: 0; width: 100%; }
    .table td { font-size: 13px; }
    .detail { min-width: 220px; font-family: var(--mono); font-size: 12px; overflow-wrap: anywhere; }
    .badge { display: inline-block; padding: 1px 8px; border-radius: 999px; font-family: var(--mono); font-size: 11.5px; font-weight: 600;
             white-space: nowrap; background: var(--surface-2); color: var(--text-muted); }
    .badge[data-tone='ok'] { background: var(--ok-soft); color: var(--ok); }
    .badge[data-tone='warn'] { background: var(--warn-soft); color: var(--warn); }
    .badge[data-tone='info'] { background: var(--info-soft); color: var(--info); }
    .empty { padding: 36px 20px; text-align: center; } .empty p { max-width: 520px; margin: 6px auto 0; font-size: 13px; }
    .foot { margin: 8px 2px 0; }
  `,
})
export class AuditTab {
  readonly entries = input<AuditEntry[]>([]);

  protected readonly kinds: { id: Kind; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'agent', label: 'Agents' },
    { id: 'policies', label: 'Policies' },
  ];
  protected readonly query = signal('');
  protected readonly kind = signal<Kind>('all');

  protected readonly shown = computed(() => {
    const q = this.query().trim().toLowerCase();
    const kind = this.kind();
    return this.entries().filter(
      (e) =>
        (kind === 'all' || e.action.startsWith(kind + '.')) &&
        (!q || `${e.action} ${e.target} ${e.detail} ${e.by}`.toLowerCase().includes(q)),
    );
  });

  protected tone(action: string): string {
    return TONE[action] ?? '';
  }

  /** "max_replans: 2 -> 1; verify_final: True -> False" -> one line per change */
  protected parts(detail: string): string[] {
    return detail ? detail.split('; ') : ['—'];
  }

  protected ago(iso: string): string {
    return agoMs(Date.now() - Date.parse(iso));
  }

  protected time(iso: string): string {
    return new Date(iso).toLocaleTimeString();
  }

  protected full(iso: string): string {
    return new Date(iso).toLocaleString();
  }

  protected exportCsv(): void {
    const cell = (v: string) => `"${v.replace(/"/g, '""')}"`;
    const rows = [['at', 'action', 'target', 'detail', 'by'], ...this.shown().map((e) => [e.at, e.action, e.target, e.detail, e.by])];
    const url = URL.createObjectURL(new Blob([rows.map((r) => r.map(cell).join(',')).join('\r\n')], { type: 'text/csv' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: `altasnim-audit-${new Date().toISOString().slice(0, 10)}.csv` });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
