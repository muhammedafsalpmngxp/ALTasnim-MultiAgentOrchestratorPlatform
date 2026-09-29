import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { StepEvent } from './api';

export type StepState = 'pending' | 'active' | 'done' | 'error';

export interface Step {
  id: string;
  label: string;
  state: StepState;
  detail?: string;
  progress?: [number, number];
  startedAt?: number;
  ms?: number;
}

/** Labels for the step ids the Rag agent reports (backend main.py: _upload_steps, _retrieve_steps). */
export const UPLOAD_STEPS: Record<string, string> = {
  read: 'Reading the file',
  chunk: 'Splitting into chunks',
  embed: 'Creating embeddings',
  store: 'Saving to the vector store',
};
export const RETRIEVE_STEPS: Record<string, string> = {
  embed: 'Understanding the question',
  search: 'Searching your documents',
  rerank: 'Ranking the best passages',
  send: 'Asking the next agents',
};

/** One event from a /stream endpoint applied to the step list: the plan lists them, then each starts and ends. */
export function applyEvent(steps: Step[], event: StepEvent, labels: Record<string, string>): Step[] {
  if (event.plan) return event.plan.map((id) => ({ id, label: labels[id] ?? id, state: 'pending' }));
  const now = performance.now();
  return steps.map((s): Step => {
    if (s.id !== event.step) return s;
    if (event.state === 'start') return { ...s, state: 'active', startedAt: now, detail: event.detail, progress: event.progress };
    if (event.state === 'progress') return { ...s, progress: event.progress };
    if (event.state === 'done') {
      const progress: [number, number] | undefined = s.progress && [s.progress[1], s.progress[1]];
      return { ...s, state: 'done', detail: event.detail ?? s.detail, progress, ms: now - (s.startedAt ?? now) };
    }
    return s;
  });
}

/** The stream ended with an error: the running step failed with that message. */
export function failSteps(steps: Step[], message: string): Step[] {
  return steps.map((s): Step => (s.state === 'active' ? { ...s, state: 'error', detail: message } : s));
}

export function seconds(ms: number | undefined): string {
  return ms == null ? '' : ms < 1000 ? `${Math.max(1, Math.round(ms))} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/**
 * The live pipeline of one upload or question: every step with its state, detail, time and (embedding) progress.
 * `open` folds it away smoothly, e.g. once the work is done.
 */
@Component({
  selector: 'alt-progress-steps',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[class.open]': 'open()', '[class.compact]': 'compact()' },
  template: `
    <div class="inner">
      <ol>
        @for (s of steps(); track s.id; let i = $index, last = $last) {
          <li [attr.data-state]="s.state" [style.animation-delay.ms]="i * 70">
            <div class="rail">
              <span class="icon">
                @switch (s.state) {
                  @case ('active') {
                    <span class="ring"></span>
                  }
                  @case ('done') {
                    <svg viewBox="0 0 24 24"><path class="tick" d="M6 12.5l4 4 8-9" /></svg>
                  }
                  @case ('error') {
                    <svg viewBox="0 0 24 24"><path class="cross" d="M8 8l8 8M16 8l-8 8" /></svg>
                  }
                }
              </span>
              @if (!last) {
                <span class="line"><span class="fill"></span></span>
              }
            </div>
            <div class="main">
              <div class="head">
                <span class="label">{{ s.label }}</span>
                @if (s.ms != null) {
                  <span class="time">{{ time(s.ms) }}</span>
                }
              </div>
              @if (s.detail) {
                <div class="detail">{{ s.detail }}</div>
              }
              @if (s.state === 'active' && s.progress; as p) {
                <div class="bar"><span [style.width.%]="p[1] ? (p[0] / p[1]) * 100 : 0"></span></div>
                <div class="detail count">{{ p[0] }} of {{ p[1] }} chunks</div>
              }
            </div>
          </li>
        }
      </ol>
    </div>
  `,
  styles: `
    :host { display: grid; grid-template-rows: 0fr; opacity: 0; transition: grid-template-rows 0.45s ease, opacity 0.35s ease; }
    :host(.open) { grid-template-rows: 1fr; opacity: 1; }
    .inner { min-height: 0; overflow: hidden; }
    ol { list-style: none; margin: 0; padding: 2px 0 0; }
    li { display: flex; gap: 12px; animation: rise 0.4s ease both; }

    .rail { display: flex; flex-direction: column; align-items: center; flex: none; width: 20px; }
    .icon {
      position: relative; display: grid; place-items: center; flex: none; width: 20px; height: 20px;
      color: var(--r-on-accent); background: var(--r-bg); border: 1.5px solid var(--r-border); border-radius: 50%;
      transition: background-color 0.3s ease, border-color 0.3s ease;
    }
    svg { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 2.8; stroke-linecap: round; stroke-linejoin: round; }
    li[data-state='active'] .icon { border-color: transparent; }
    li[data-state='active'] .icon::after {
      content: ''; position: absolute; inset: -6px; border-radius: 50%;
      background: var(--r-text); opacity: 0.08; animation: breathe 1.6s ease-in-out infinite;
    }
    .ring {
      position: absolute; inset: -1.5px; border-radius: 50%;
      border: 2px solid var(--r-border); border-top-color: var(--r-text); animation: spin 0.75s linear infinite;
    }
    li[data-state='done'] .icon { background: var(--r-accent); border-color: var(--r-accent); animation: pop 0.4s ease; }
    li[data-state='error'] .icon { background: var(--r-danger); border-color: var(--r-danger); color: #fff; animation: pop 0.4s ease; }
    .tick, .cross { stroke-dasharray: 24; stroke-dashoffset: 24; animation: draw 0.35s 0.12s ease forwards; }
    .line { position: relative; flex: 1; width: 2px; min-height: 12px; margin: 3px 0; overflow: hidden; background: var(--r-border); border-radius: 1px; }
    .fill { position: absolute; inset: 0; background: var(--r-accent); transform: scaleY(0); transform-origin: top; transition: transform 0.5s ease; }
    li[data-state='done'] .fill { transform: scaleY(1); }

    .main { flex: 1; min-width: 0; padding-bottom: 14px; }
    li:last-child .main { padding-bottom: 4px; }
    .head { display: flex; align-items: baseline; gap: 8px; font-size: 14px; line-height: 20px; }
    .label { color: var(--r-faint); transition: color 0.3s ease; }
    li[data-state='active'] .label {
      font-weight: 500; color: transparent;
      background: linear-gradient(90deg, var(--r-text) 0%, var(--r-text) 40%, var(--r-faint) 50%, var(--r-text) 60%, var(--r-text) 100%);
      background-size: 300% 100%; -webkit-background-clip: text; background-clip: text; animation: shimmer 2s linear infinite;
    }
    li[data-state='done'] .label { color: var(--r-text); }
    li[data-state='error'] .label { color: var(--r-danger); }
    .time { margin-left: auto; font-size: 12px; color: var(--r-faint); font-variant-numeric: tabular-nums; animation: fade 0.3s ease both; }
    .detail { font-size: 12.5px; line-height: 1.5; color: var(--r-faint); overflow-wrap: anywhere; animation: fade 0.35s ease both; }
    li[data-state='error'] .detail { color: var(--r-danger); }
    .count { font-variant-numeric: tabular-nums; }
    .bar { position: relative; height: 4px; margin: 7px 0 3px; overflow: hidden; background: var(--r-border); border-radius: 2px; }
    .bar span { position: absolute; inset: 0 auto 0 0; overflow: hidden; background: var(--r-accent); border-radius: 2px; transition: width 0.45s ease; }
    .bar span::after {
      content: ''; position: absolute; inset: 0;
      background: linear-gradient(90deg, transparent, rgba(128, 128, 128, 0.55), transparent); animation: sweep 1.3s linear infinite;
    }

    :host(.compact) .head { font-size: 12.5px; line-height: 16px; }
    :host(.compact) .main { padding-bottom: 8px; }
    :host(.compact) li { gap: 10px; }
    :host(.compact) .rail, :host(.compact) .icon { width: 16px; }
    :host(.compact) .icon { height: 16px; }
    :host(.compact) svg { width: 10px; height: 10px; }
    :host(.compact) .detail { font-size: 11.5px; }

    @keyframes rise { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: none; } }
    @keyframes fade { from { opacity: 0; } to { opacity: 1; } }
    @keyframes spin { to { transform: rotate(360deg); } }
    @keyframes breathe { 0%, 100% { opacity: 0.04; transform: scale(0.8); } 50% { opacity: 0.14; transform: scale(1.1); } }
    @keyframes pop { 0% { transform: scale(0.6); } 60% { transform: scale(1.15); } 100% { transform: scale(1); } }
    @keyframes draw { to { stroke-dashoffset: 0; } }
    @keyframes shimmer { from { background-position: 100% 0; } to { background-position: 0% 0; } }
    @keyframes sweep { from { transform: translateX(-100%); } to { transform: translateX(100%); } }
    @media (prefers-reduced-motion: reduce) {
      :host, *, *::before, *::after { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; transition-duration: 0.01ms !important; }
    }
  `,
})
export class ProgressSteps {
  readonly steps = input.required<Step[]>();
  readonly open = input(true);
  readonly compact = input(false);
  protected readonly time = seconds;
}
