import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { AgentResult, FLOW_ICONS, FlowIcon, StatusBadge, StepResult } from '@altasnim/shared';

export interface StepRow {
  id: string;
  agent: string;
  objective: string;
  result: AgentResult;
  icon: FlowIcon;
  duration: string | null;
}

/** Every finished step: agent, objective, duration and status; expands to its result (failures start open). */
@Component({
  selector: 'alt-step-list',
  imports: [StatusBadge, StepResult],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="card">
      <div class="head">
        <h2>Step results</h2>
        @if (total()) {
          <span class="muted small">{{ rows().length }} of {{ total() }} steps</span>
        }
      </div>
      <div class="steps">
        @for (s of rows(); track s.id) {
          <details class="step" [open]="s.result.status !== 'ok'">
            <summary>
              <span class="icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path [attr.d]="icons[s.icon]" /></svg></span>
              <span class="name"><strong>{{ s.agent }}</strong><code>{{ s.id }}</code></span>
              <span class="obj">{{ s.objective }}</span>
              @if (s.duration) {
                <span class="dur">{{ s.duration }}</span>
              }
              <alt-status-badge [status]="s.result.status" />
              <svg class="chev" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
            </summary>
            <div class="body"><alt-step-result [result]="s.result" [header]="false" /></div>
          </details>
        } @empty {
          <p class="none">Steps appear here as the agents finish.</p>
        }
      </div>
    </section>
  `,
  styles: `
    .head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
    .head h2 { margin: 0; }
    .small { font-size: 12px; }
    .steps { display: flex; flex-direction: column; gap: 8px; }
    .none { margin: 0; padding: 8px 0; color: var(--text-muted); }
    .step { border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface); animation: rise 0.35s ease both; }
    summary { display: flex; align-items: center; gap: 12px; min-height: 52px; padding: 8px 14px; cursor: pointer; list-style: none; }
    summary::-webkit-details-marker { display: none; }
    summary:hover { background: var(--surface-2); border-radius: var(--radius-sm); }
    .icon { display: grid; place-items: center; flex: none; width: 32px; height: 32px; border-radius: 9px; color: var(--primary); background: var(--primary-soft); }
    .icon svg { width: 17px; height: 17px; fill: none; stroke: currentColor; stroke-width: 1.9; stroke-linecap: round; stroke-linejoin: round; }
    .name { display: flex; align-items: baseline; gap: 6px; flex: none; }
    .obj { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; color: var(--text-muted); }
    .dur { font-family: var(--mono); font-size: 12px; color: var(--text-muted); }
    .chev { flex: none; fill: none; stroke: var(--text-muted); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; transition: transform 0.2s ease; }
    .step[open] .chev { transform: rotate(180deg); }
    .body { padding: 4px 16px 14px 58px; animation: rise 0.25s ease both; }
    @container (max-width: 700px) { .obj, .dur { display: none; } .body { padding-left: 16px; } }
    @keyframes rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
    @media (prefers-reduced-motion: reduce) { .step, .body { animation: none; } }
  `,
})
export class StepList {
  readonly rows = input<StepRow[]>([]);
  readonly total = input(0);
  protected readonly icons = FLOW_ICONS;
}
