import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';

import { FIX_LABEL, VerifyCall, verdictOf } from './verify-call';

/** Right pane: one check. The question, the answer, the verdict and each part of the question. */
@Component({
  selector: 'vf-call-detail',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let c = call();
    @let r = c.result;
    <article>
      <p class="eyebrow">User question</p>
      <h2 class="question">{{ c.question || '(no question)' }}</h2>

      <dl class="meta">
        <div><dt>Checked</dt><dd>{{ received() }}</dd></div>
        <div><dt>Check step</dt><dd><code>{{ c.task_id || '—' }}</code></dd></div>
        <div><dt>Answer step</dt><dd><code>{{ c.answer_step || '—' }}</code></dd></div>
        <div><dt>Took</dt><dd>{{ c.duration_ms != null ? c.duration_ms + ' ms' : '—' }}</dd></div>
      </dl>

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
          } @else if (r && !r.passed && r.issues.length) {
            <ul>
              @for (i of r.issues; track $index) { <li>{{ i }}</li> }
            </ul>
          } @else if (r) {
            <p>{{ r.summary }}</p>
          }
          @if (r && !r.passed) {
            <p class="next"><strong>Next:</strong> {{ fixLabel() }}@if (redo()) { · redo <code>{{ redo() }}</code> }</p>
          }
        </div>
      </section>
      @for (w of r?.warnings ?? []; track $index) {
        <div class="warning"><strong>Warning</strong> {{ w }}</div>
      }

      @if (r?.parts?.length) {
        <section class="block">
          <header class="bh">
            <h4>Parts of the question</h4>
            <span class="muted">{{ answeredCount() }} of {{ factParts().length }} answered</span>
          </header>
          <div class="checks">
            @for (p of r!.parts!; track $index) {
              <div class="check" [class.bad]="!p.answered && p.kind !== 'action'" [class.action]="p.kind === 'action'"
                   [attr.title]="p.kind === 'action' ? 'an action: done after the check' : null">
                <span class="mark" aria-hidden="true">{{ p.kind === 'action' ? '→' : p.answered ? '✓' : '✕' }}</span>
                {{ p.part }}
              </div>
            }
          </div>
        </section>
      }

      <section class="block">
        <header class="bh"><h4>The answer</h4></header>
        <pre class="summary">{{ c.answer || '(empty)' }}</pre>
      </section>

      <section class="block">
        <header class="bh">
          <h4>Raw result</h4>
          <div class="tabs"><button type="button" class="copy" (click)="copy()">{{ copied() ? 'Copied' : 'Copy' }}</button></div>
        </header>
        <pre class="raw">{{ rawText() }}</pre>
      </section>
    </article>
  `,
  styles: `
    :host { display: block; }
    article { max-width: 920px; margin: 0 auto; padding: 28px 32px 48px; }
    .eyebrow { margin: 0 0 6px; font-size: 11.5px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--text-muted); }
    .question { font-size: 22px; line-height: 1.3; font-weight: 650; letter-spacing: -.01em; margin: 0 0 18px; color: var(--text); white-space: pre-wrap; }
    .meta { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin: 0; background: var(--border);
            border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
    .meta div { background: var(--surface); padding: 10px 14px; min-width: 0; }
    .meta dt { font-size: 11.5px; color: var(--text-muted); }
    .meta dd { margin: 2px 0 0; font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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
    .vt { min-width: 0; }
    .vt h3 { margin: 2px 0 4px; font-size: 16px; }
    .verdict[data-v='passed'] h3 { color: var(--ok); }
    .verdict[data-v='failed'] h3, .verdict[data-v='error'] h3 { color: var(--danger); }
    .vt p, .vt ul { margin: 0; color: var(--text); font-size: 13.5px; }
    .vt ul { padding-left: 18px; }
    .vt .next { margin-top: 10px; font-size: 13px; }
    .warning { margin-top: 10px; padding: 10px 14px; border-radius: 10px; background: var(--warn-soft); color: var(--warn); font-size: 13px; }

    .block { margin-top: 26px; }
    .bh { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; flex-wrap: wrap; }
    .bh h4 { margin: 0; font-size: 13px; font-weight: 650; letter-spacing: .02em; }
    .muted { color: var(--text-muted); font-size: 12.5px; }

    .checks { display: flex; flex-wrap: wrap; gap: 8px; }
    .check { display: inline-flex; align-items: center; gap: 7px; padding: 6px 12px 6px 8px; border-radius: 999px; font-size: 12.5px;
             font-weight: 500; background: var(--surface); border: 1px solid var(--border); }
    .mark { width: 18px; height: 18px; border-radius: 50%; display: grid; place-items: center; font-size: 11px; font-weight: 700;
            background: var(--ok-soft); color: var(--ok); }
    .check.bad { border-color: color-mix(in srgb, var(--danger) 35%, transparent); color: var(--danger); }
    .check.bad .mark { background: var(--danger-soft); color: var(--danger); }
    .check.action .mark { background: var(--surface-2); color: var(--text-muted); }

    .summary, .raw { margin: 0; padding: 14px 16px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px;
                     white-space: pre-wrap; word-break: break-word; font-size: 12.5px; line-height: 1.6; max-height: 420px; overflow: auto; }
    .raw { font-size: 12px; }
    .tabs .copy { font: inherit; font-size: 12.5px; font-weight: 500; padding: 4px 10px; border-radius: 6px; cursor: pointer;
                  border: 1px solid var(--border); background: var(--surface); color: var(--text); }
    .tabs .copy:hover { background: var(--surface-2); }

    @media (max-width: 760px) {
      article { padding: 20px 16px 36px; }
      .question { font-size: 19px; }
      .meta { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
  `,
})
export class CallDetail {
  readonly call = input.required<VerifyCall>();

  protected readonly copied = signal(false);

  protected readonly verdict = computed(() => verdictOf(this.call()));
  protected readonly received = computed(() =>
    new Date(this.call().received_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'medium' }),
  );
  protected readonly verdictTitle = computed(
    () => ({ passed: 'Answer matches the question', failed: 'Answer does not match', error: 'Verifier error', running: 'Checking…' })[this.verdict()],
  );
  protected readonly fixLabel = computed(() => FIX_LABEL[this.call().result?.fix ?? 'none'] ?? '');
  protected readonly redo = computed(() => (this.call().result?.rejected_steps ?? []).join(', '));
  protected readonly factParts = computed(() => (this.call().result?.parts ?? []).filter((p) => p.kind !== 'action'));
  protected readonly answeredCount = computed(() => this.factParts().filter((p) => p.answered).length);
  protected readonly rawText = computed(() => JSON.stringify(this.call().result ?? null, null, 2));

  protected async copy(): Promise<void> {
    await navigator.clipboard?.writeText(this.rawText());
    this.copied.set(true);
    setTimeout(() => this.copied.set(false), 1500);
  }
}
