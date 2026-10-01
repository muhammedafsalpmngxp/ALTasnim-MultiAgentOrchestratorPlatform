import { ChangeDetectionStrategy, Component, input } from '@angular/core';

export type Tone = 'info' | 'ok' | 'warn' | 'danger' | 'primary' | 'muted';

export interface TimelineItem {
  at: string;
  text: string;
  tone: Tone;
  icon: string;
}

/** The run's live events as a vertical timeline, newest at the bottom (each slides in). */
@Component({
  selector: 'alt-activity-timeline',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="card activity">
      <div class="head">
        <h2>Live activity</h2>
        @if (live()) {
          <span class="live"><i></i>live</span>
        }
      </div>
      <ol>
        @for (t of items(); track $index) {
          <li [attr.data-tone]="t.tone">
            <span class="icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path [attr.d]="t.icon" /></svg></span>
            <div class="body">
              <span class="text">{{ t.text }}</span>
              <span class="time">{{ t.at }}</span>
            </div>
          </li>
        } @empty {
          <li class="none">Events appear here while the flow runs.</li>
        }
      </ol>
    </section>
  `,
  styles: `
    :host { display: block; }
    .activity { display: flex; flex-direction: column; max-height: inherit; }
    .head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
    .head h2 { margin: 0; }
    .live { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--info); }
    .live i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; animation: ping 1.3s ease-in-out infinite; }
    ol { flex: 1; min-height: 0; overflow-y: auto; list-style: none; margin: 0; padding: 0 2px 0 0; }
    li { position: relative; display: flex; gap: 10px; padding: 0 0 14px; animation: slide-in 0.35s cubic-bezier(0.2, 0.8, 0.3, 1) both; }
    li:not(:last-child)::before { content: ''; position: absolute; left: 13px; top: 28px; bottom: 2px; width: 2px; border-radius: 1px; background: var(--border); }
    li.none { padding: 8px 0; color: var(--text-muted); animation: none; }
    .icon { display: grid; place-items: center; flex: none; width: 28px; height: 28px; border-radius: 50%; color: var(--text-muted); background: var(--surface-2); }
    .icon svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
    li[data-tone='primary'] .icon { color: var(--primary); background: var(--primary-soft); }
    li[data-tone='info'] .icon { color: var(--info); background: var(--info-soft); }
    li[data-tone='ok'] .icon { color: var(--ok); background: var(--ok-soft); }
    li[data-tone='warn'] .icon { color: var(--warn); background: var(--warn-soft); }
    li[data-tone='danger'] .icon { color: var(--danger); background: var(--danger-soft); }
    .body { display: flex; flex-direction: column; min-width: 0; padding-top: 3px; }
    .text { font-size: 13px; line-height: 1.4; overflow-wrap: anywhere; }
    .time { font-family: var(--mono); font-size: 11px; color: var(--text-faint); }
    @keyframes slide-in { from { opacity: 0; transform: translateX(-8px); } to { opacity: 1; transform: none; } }
    @keyframes ping { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(0.75); } }
    @media (prefers-reduced-motion: reduce) { li, .live i { animation: none; } }
  `,
})
export class ActivityTimeline {
  readonly items = input<TimelineItem[]>([]);
  readonly live = input(false);
}
