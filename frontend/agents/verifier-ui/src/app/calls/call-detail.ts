import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';

import { VerifyCall, checkedSteps, verdictOf } from './verify-call';

type RawTab = 'payload' | 'result' | 'task';

/** Right pane: everything about one call. */
@Component({
  selector: 'vf-call-detail',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let c = call();
    <article>
      <p class="eyebrow">Question</p>
      <h2 class="question">{{ c.question || '(no question)' }}</h2>

      <dl class="meta">
        <div><dt>Received</dt><dd>{{ received() }}</dd></div>
        <div><dt>From</dt><dd><code>{{ c.client }}</code></dd></div>
        <div><dt>Task</dt><dd><code>{{ c.task.task_id || '—' }}</code></dd></div>
        <div><dt>Verified in</dt><dd>{{ c.duration_ms != null ? c.duration_ms + ' ms' : '—' }}</dd></div>
      </dl>
      @if (c.task.objective) {
        <p class="objective"><span>Objective</span>{{ c.task.objective }}</p>
      }

      <section class="verdict" [attr.data-v]="verdict()">
        <div class="icon" aria-hidden="true">
          @switch (verdict()) {
            @case ('passed') { <svg viewBox="0 0 24 24"><path d="M9.5 16.2 5.3 12l-1.4 1.4 5.6 5.6 11-11-1.4-1.4z"/></svg> }
            @case ('running') { <span class="spin"></span> }
            @default { <svg viewBox="0 0 24 24"><path d="M18.3 5.7 12 12l6.3 6.3-1.4 1.4L10.6 13.4 4.3 19.7 2.9 18.3 9.2 12 2.9 5.7 4.3 4.3l6.3 6.3 6.3-6.3z"/></svg> }
          }
        </div>
        <div class="vt">
          <h3>{{ verdictTitle() }}</h3>
          @if (c.error) {
            <p>{{ c.error }}</p>
          } @else if (c.result?.issues?.length) {
            <ul>
              @for (i of c.result!.issues; track i) { <li>{{ i }}</li> }
            </ul>
          } @else if (c.result) {
            <p>All checks passed for {{ steps().length }} {{ steps().length === 1 ? 'input' : 'inputs' }}.</p>
          }
        </div>
      </section>
      @for (w of c.result?.warnings ?? []; track w) {
        <div class="warning"><strong>Warning</strong> {{ w }}</div>
      }

      @for (s of steps(); track s.id) {
        <section class="block">
          <header class="bh">
            <h4>Checks</h4>
            <span class="muted">input <code>{{ s.id }}</code></span>
          </header>
          <div class="checks">
            @for (k of s.checks; track k.label) {
              <div class="check" [class.bad]="!k.passed" [attr.title]="k.detail || null">
                <span class="mark" aria-hidden="true">{{ k.passed ? '✓' : '✕' }}</span>{{ k.label }}
              </div>
            }
          </div>
        </section>

        <section class="block">
          <header class="bh">
            <h4>Evidence</h4>
            <span class="muted">{{ s.findings.length }} {{ s.findings.length === 1 ? 'result' : 'results' }} · {{ s.sources.length }} sources</span>
          </header>
          @if (s.findings.length) {
            <ol class="results">
              @for (f of s.findings; track f.rank) {
                <li>
                  <div class="avatar" [style.background]="tint(f.domain)" aria-hidden="true">{{ f.domain.charAt(0).toUpperCase() }}</div>
                  <div class="rb">
                    <div class="rt">
                      <span class="rank">#{{ f.rank }}</span>
                      <span class="domain">{{ f.domain }}</span>
                    </div>
                    <a class="title" [href]="f.url" target="_blank" rel="noopener">{{ f.title || f.url }}</a>
                    @if (f.content) { <p class="snippet">{{ f.content }}</p> }
                  </div>
                </li>
              }
            </ol>
          } @else if (s.summary) {
            <pre class="summary">{{ s.summary }}</pre>
          } @else {
            <p class="muted">No findings were sent.</p>
          }
        </section>
      } @empty {
        <section class="block"><p class="muted">No inputs were sent, so there was nothing to verify.</p></section>
      }

      <section class="block">
        <header class="bh">
          <h4>Raw data</h4>
          <div class="tabs" role="tablist">
            @for (t of rawTabs; track t.value) {
              <button type="button" role="tab" [class.on]="rawTab() === t.value" [attr.aria-selected]="rawTab() === t.value"
                      (click)="rawTab.set(t.value)">{{ t.label }}</button>
            }
            <button type="button" class="copy" (click)="copy()">{{ copied() ? 'Copied' : 'Copy' }}</button>
          </div>
        </header>
        <pre class="raw">{{ rawText() }}</pre>
      </section>
    </article>
  `,
  styles: `
    :host { display: block; }
    article { max-width: 920px; margin: 0 auto; padding: 28px 32px 48px; }
    .eyebrow { margin: 0 0 6px; font-size: 11.5px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--text-muted); }
    .question { font-size: 24px; line-height: 1.3; font-weight: 650; letter-spacing: -.01em; margin: 0 0 18px; color: var(--text); }
    .meta { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin: 0; background: var(--border);
            border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
    .meta div { background: var(--surface); padding: 10px 14px; min-width: 0; }
    .meta dt { font-size: 11.5px; color: var(--text-muted); }
    .meta dd { margin: 2px 0 0; font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .objective { margin: 12px 0 0; color: var(--text-muted); font-size: 13px; }
    .objective span { font-weight: 600; color: var(--text); margin-right: 8px; }
    code { background: var(--surface-2); padding: 1px 6px; border-radius: 4px; font-size: 12px; }

    .verdict { display: flex; gap: 14px; margin-top: 22px; padding: 18px; border-radius: 12px; border: 1px solid var(--border); background: var(--surface); }
    .verdict[data-v='passed'] { background: var(--ok-soft); border-color: color-mix(in srgb, var(--ok) 25%, transparent); }
    .verdict[data-v='failed'], .verdict[data-v='error'] { background: var(--danger-soft); border-color: color-mix(in srgb, var(--danger) 25%, transparent); }
    .icon { flex: none; width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; background: var(--text-muted); }
    .verdict[data-v='passed'] .icon { background: var(--ok); }
    .verdict[data-v='failed'] .icon, .verdict[data-v='error'] .icon { background: var(--danger); }
    .icon svg { width: 22px; height: 22px; fill: #fff; }
    .spin { width: 18px; height: 18px; border: 2px solid #fff; border-right-color: transparent; border-radius: 50%; animation: spin .8s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .vt h3 { margin: 2px 0 4px; font-size: 16px; }
    .verdict[data-v='passed'] h3 { color: var(--ok); }
    .verdict[data-v='failed'] h3, .verdict[data-v='error'] h3 { color: var(--danger); }
    .vt p, .vt ul { margin: 0; color: var(--text); font-size: 13.5px; }
    .vt ul { padding-left: 18px; }
    .warning { margin-top: 10px; padding: 10px 14px; border-radius: 10px; background: var(--warn-soft); color: var(--warn); font-size: 13px; }

    .block { margin-top: 26px; }
    .bh { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; flex-wrap: wrap; }
    .bh h4 { margin: 0; font-size: 13px; font-weight: 650; letter-spacing: .02em; }
    .bh .muted { font-size: 12.5px; }
    .muted { color: var(--text-muted); }

    .checks { display: flex; flex-wrap: wrap; gap: 8px; }
    .check { display: inline-flex; align-items: center; gap: 7px; padding: 6px 12px 6px 8px; border-radius: 999px; font-size: 12.5px;
             font-weight: 500; background: var(--surface); border: 1px solid var(--border); }
    .mark { width: 18px; height: 18px; border-radius: 50%; display: grid; place-items: center; font-size: 11px; font-weight: 700;
            background: var(--ok-soft); color: var(--ok); }
    .check.bad { border-color: color-mix(in srgb, var(--danger) 35%, transparent); color: var(--danger); }
    .check.bad .mark { background: var(--danger-soft); color: var(--danger); }

    .results { list-style: none; margin: 0; padding: 0; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); overflow: hidden; }
    .results li { display: flex; gap: 14px; padding: 16px 18px; }
    .results li + li { border-top: 1px solid var(--border); }
    .avatar { flex: none; width: 34px; height: 34px; border-radius: 9px; display: grid; place-items: center; color: #fff; font-weight: 700; font-size: 14px; }
    .rb { min-width: 0; }
    .rt { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--text-muted); }
    .rank { font-weight: 700; color: var(--text); }
    .title { display: block; margin-top: 2px; font-weight: 600; font-size: 14.5px; color: var(--primary); text-decoration: none; }
    .title:hover { text-decoration: underline; }
    .snippet { margin: 6px 0 0; color: var(--text); font-size: 13.5px; line-height: 1.55; }
    .summary, .raw { margin: 0; padding: 14px 16px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px;
                     white-space: pre-wrap; word-break: break-word; font-size: 12px; line-height: 1.6; max-height: 420px; overflow: auto; }

    .tabs { display: flex; gap: 4px; }
    .tabs button { font: inherit; font-size: 12.5px; font-weight: 500; border: 1px solid transparent; background: transparent; color: var(--text-muted);
                   padding: 4px 10px; border-radius: 6px; cursor: pointer; }
    .tabs button.on { background: var(--surface); border-color: var(--border); color: var(--text); }
    .tabs .copy { margin-left: 6px; border-color: var(--border); background: var(--surface); color: var(--text); }
    .tabs .copy:hover { background: var(--surface-2); }

    @media (max-width: 760px) {
      article { padding: 20px 16px 36px; }
      .question { font-size: 20px; }
      .meta { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
  `,
})
export class CallDetail {
  readonly call = input.required<VerifyCall>();

  protected readonly rawTabs: { value: RawTab; label: string }[] = [
    { value: 'payload', label: 'Payload' },
    { value: 'result', label: 'Result' },
    { value: 'task', label: 'Task' },
  ];
  protected readonly rawTab = signal<RawTab>('payload');
  protected readonly copied = signal(false);

  protected readonly verdict = computed(() => verdictOf(this.call()));
  protected readonly steps = computed(() => checkedSteps(this.call()));
  protected readonly received = computed(() =>
    new Date(this.call().received_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'medium' }),
  );
  protected readonly verdictTitle = computed(
    () => ({ passed: 'Verification passed', failed: 'Verification failed', error: 'Verifier error', running: 'Verifying…' })[this.verdict()],
  );
  protected readonly rawText = computed(() => {
    const c = this.call();
    const value = { payload: c.payload, result: c.result ?? null, task: c.task }[this.rawTab()];
    return JSON.stringify(value, null, 2);
  });

  protected async copy(): Promise<void> {
    await navigator.clipboard?.writeText(this.rawText());
    this.copied.set(true);
    setTimeout(() => this.copied.set(false), 1500);
  }

  /** Stable, readable colour per domain. */
  protected tint(domain: string): string {
    let h = 0;
    for (const ch of domain) h = (h * 31 + ch.charCodeAt(0)) % 360;
    return `hsl(${h} 55% 45%)`;
  }
}
