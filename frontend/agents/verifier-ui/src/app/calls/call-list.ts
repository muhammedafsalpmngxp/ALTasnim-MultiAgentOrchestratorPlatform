import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { VerdictFilter, VerifyCallsStore } from './verify-calls.store';
import { VerifyCall, timeAgo, verdictOf } from './verify-call';

/** Left pane: search, verdict filter and the list of received calls. */
@Component({
  selector: 'vf-call-list',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="tools">
      <label class="search">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M8.5 3a5.5 5.5 0 1 0 3.4 9.8l3.6 3.7 1.1-1.1-3.7-3.6A5.5 5.5 0 0 0 8.5 3Zm0 1.5a4 4 0 1 1 0 8 4 4 0 0 1 0-8Z"/></svg>
        <input type="search" placeholder="Search question or step" [value]="store.query()"
               (input)="store.query.set($any($event.target).value)" aria-label="Search calls" />
      </label>
      <div class="seg" role="tablist" aria-label="Filter by verdict">
        @for (f of filters; track f.value) {
          <button type="button" role="tab" [class.on]="store.filter() === f.value"
                  [attr.aria-selected]="store.filter() === f.value" (click)="setFilter(f.value)">{{ f.label }}</button>
        }
      </div>
    </div>

    @if (store.hasNewer()) {
      <button type="button" class="newer" (click)="store.followLatest()">↑ New call received · show latest</button>
    }

    <ul class="list" role="listbox" aria-label="Received calls">
      @for (c of store.filtered(); track c.id) {
        <li role="option" [attr.aria-selected]="c.id === store.selected()?.id" [class.sel]="c.id === store.selected()?.id"
            tabindex="0" (click)="store.select(c.id)" (keydown.enter)="store.select(c.id)">
          <span class="bar" [attr.data-v]="verdict(c)"></span>
          <div class="q">{{ c.question || '(no question)' }}</div>
          <div class="sub">
            <span class="chip" [attr.data-v]="verdict(c)">{{ verdict(c) }}</span>
            <span>{{ ago(c) }}</span>
            @if (c.task_id) { <span class="dot">·</span><span>{{ c.task_id }}</span> }
          </div>
        </li>
      } @empty {
        <li class="none">{{ store.calls().length ? 'No calls match your filter.' : 'No calls yet.' }}</li>
      }
    </ul>
  `,
  styles: `
    :host { display: flex; flex-direction: column; min-height: 0; }
    .tools { padding: 14px; display: flex; flex-direction: column; gap: 10px; border-bottom: 1px solid var(--border); }
    .search { display: flex; align-items: center; gap: 8px; padding: 0 10px; height: 36px; border: 1px solid var(--border);
              border-radius: 8px; background: var(--surface); transition: border-color .15s, box-shadow .15s; }
    .search:focus-within { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-soft); }
    .search svg { width: 16px; height: 16px; fill: var(--text-muted); flex: none; }
    .search input { border: 0; outline: 0; font: inherit; flex: 1; min-width: 0; background: transparent; color: var(--text); }
    .seg { display: grid; grid-template-columns: repeat(3, 1fr); background: var(--surface-2); border-radius: 8px; padding: 3px; }
    .seg button { font: inherit; font-size: 12.5px; font-weight: 500; border: 0; background: transparent; color: var(--text-muted);
                  padding: 5px 0; border-radius: 6px; cursor: pointer; }
    .seg button.on { background: var(--surface); color: var(--text); box-shadow: 0 1px 2px rgba(16,24,40,.08); }
    .newer { margin: 10px 14px 0; font: inherit; font-size: 12.5px; font-weight: 600; color: var(--primary);
             background: var(--primary-soft); border: 0; border-radius: 8px; padding: 7px; cursor: pointer; }
    .list { list-style: none; margin: 0; padding: 6px; overflow-y: auto; flex: 1; }
    li { position: relative; padding: 11px 12px 11px 16px; border-radius: 8px; cursor: pointer; outline: none; }
    li + li { margin-top: 2px; }
    li:hover { background: var(--surface-2); }
    li:focus-visible { box-shadow: inset 0 0 0 2px var(--primary); }
    li.sel { background: var(--primary-soft); }
    .bar { position: absolute; left: 5px; top: 12px; bottom: 12px; width: 3px; border-radius: 3px; background: var(--border); }
    .bar[data-v='passed'] { background: var(--ok); }
    .bar[data-v='failed'], .bar[data-v='error'] { background: var(--danger); }
    .q { font-weight: 550; color: var(--text); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .sub { display: flex; align-items: center; gap: 6px; margin-top: 5px; font-size: 12px; color: var(--text-muted); }
    .dot { opacity: .6; }
    .chip { font-size: 11px; font-weight: 600; text-transform: capitalize; padding: 1px 7px; border-radius: 999px;
            background: var(--surface-2); color: var(--text-muted); }
    .chip[data-v='passed'] { background: var(--ok-soft); color: var(--ok); }
    .chip[data-v='failed'], .chip[data-v='error'] { background: var(--danger-soft); color: var(--danger); }
    .none { color: var(--text-muted); text-align: center; padding: 32px 12px; cursor: default; }
    .none:hover { background: none; }
  `,
})
export class CallList {
  protected readonly store = inject(VerifyCallsStore);
  protected readonly filters: { value: VerdictFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'passed', label: 'Passed' },
    { value: 'failed', label: 'Failed' },
  ];

  protected setFilter(f: VerdictFilter): void {
    this.store.filter.set(f);
    this.store.followLatest();
  }

  protected verdict(c: VerifyCall) {
    return verdictOf(c);
  }

  protected ago(c: VerifyCall): string {
    return timeAgo(c.received_at, this.store.now());
  }

}
