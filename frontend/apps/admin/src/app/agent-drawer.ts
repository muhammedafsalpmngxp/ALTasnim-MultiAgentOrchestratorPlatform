import { ChangeDetectionStrategy, Component, ElementRef, afterNextRender, computed, inject, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AgentAdmin, AgentAdminAction, AgentCardView } from '@altasnim/shared';

import { STATUS, Sample, Ui, agoMs } from './admin-utils';
import { PlanningEditor } from './planning-editor';

const W = 320;
const H = 64;

/** One agent in full: status, response time over this session's checks, connection, error, card and actions. */
@Component({
  selector: 'alt-agent-drawer',
  imports: [AgentCardView, PlanningEditor, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '(document:keydown.escape)': 'closed.emit()' },
  template: `
    <div class="backdrop" (click)="closed.emit()"></div>
    <aside class="drawer" role="dialog" aria-modal="true" [attr.aria-label]="agent().name + ' details'" tabindex="-1"
>
      <header>
        <div class="min">
          <div class="title"><h2>{{ agent().name }}</h2>@if (agent().card?.version) {<span class="faint">v{{ agent().card!.version }}</span>}</div>
          <span class="pill" [attr.data-tone]="tone()"><span class="dot"></span>{{ label() }}</span>
        </div>
        <button class="btn btn-ghost btn-sm close" (click)="closed.emit()" aria-label="Close">✕</button>
      </header>

      <div class="scroll">
        @if (agent().node) {
          <div class="row">
            <button class="btn btn-sm" [disabled]="!!busy()" (click)="act.emit('recheck')">{{ busy() === 'recheck' ? 'Checking…' : 'Re-check' }}</button>
            @if (agent().paused) {
              <button class="btn btn-sm btn-primary" [disabled]="!!busy()" (click)="act.emit('resume')">Resume</button>
            } @else {
              <button class="btn btn-sm" [disabled]="!!busy()" (click)="act.emit('pause')">Pause planning</button>
            }
            @if (ui()) { <a class="btn btn-sm btn-ghost" [routerLink]="page()">Open UI</a> }
            @if (agent().url; as url) {
              <a class="btn btn-sm btn-ghost" [href]="url + '/docs'" target="_blank" rel="noopener">API docs ↗</a>
              <a class="btn btn-sm btn-ghost" [href]="studio(url)" target="_blank" rel="noopener">Studio ↗</a>
            }
          </div>
        }

        @if (agent().error; as err) {
          <div class="err">{{ err }}</div>
        }

        <section class="stats">
          <div><span class="k">Response</span><span class="v">{{ agent().latency_ms != null ? agent().latency_ms + ' ms' : '—' }}</span></div>
          <div><span class="k">Average</span><span class="v">{{ chart().avg != null ? chart().avg + ' ms' : '—' }}</span></div>
          <div><span class="k">Availability</span><span class="v">{{ chart().availability ?? '—' }}</span></div>
          <div><span class="k">Last check</span><span class="v">{{ agent().checked_at ? ago(agent().checked_at!) : '—' }}</span></div>
        </section>

        <section>
          <h3>Response time <span class="faint">· {{ samples().length }} check{{ samples().length === 1 ? '' : 's' }} this session</span></h3>
          @if (chart().points.length > 1) {
            <svg [attr.viewBox]="'0 0 ' + w + ' ' + h" preserveAspectRatio="none" class="spark" role="img"
                 [attr.aria-label]="'Response time, max ' + chart().max + ' ms'">
              <path class="area" [attr.d]="chart().area" />
              <polyline class="line" [attr.points]="chart().line" />
              @for (p of chart().points; track $index) {
                @if (!p.up) { <circle class="down" [attr.cx]="p.x" [attr.cy]="h - 4" r="3" /> }
              }
            </svg>
            <div class="axis faint"><span>{{ chart().from }}</span><span>max {{ chart().max }} ms</span><span>now</span></div>
          } @else {
            <p class="faint small">The chart fills in as the supervisor checks the agent (about every minute while this page is open).</p>
          }
        </section>

        <section>
          <h3>Connection</h3>
          <dl>
            <dt>Port</dt><dd class="mono">{{ agent().port ?? '—' }}</dd>
            <dt>Graph</dt><dd class="mono">{{ agent().graph_id ?? '—' }}</dd>
            <dt>Machine</dt><dd class="mono">{{ agent().url ?? (agent().status === 'in_process' ? 'in the supervisor process' : 'not found on the network') }}</dd>
            <dt>Found by</dt><dd>{{ agent().pinned_url ? 'pinned URL (AGENT_' + agent().name.toUpperCase() + '_URL)' : 'network search: port + graph' }}</dd>
            <dt>UI</dt><dd class="mono">{{ ui() ? ui()!.name + ' :' + ui()!.port + (ui()!.up === false ? ' (down)' : '') : '—' }}</dd>
            <dt>Owner</dt><dd>{{ agent().card?.owner || '—' }}</dd>
          </dl>
        </section>

        @if (agent().node) {
          <section class="planning">
            <alt-planning-editor [agent]="agent()" (saved)="updated.emit($event)" />
          </section>
        }

        <section>
          <h3>Agent card</h3>
          @if (agent().card; as card) {
            <alt-agent-card [card]="card" />
          } @else {
            <p class="faint small">No card: the supervisor plans without this agent until it answers.</p>
          }
        </section>
      </div>
    </aside>
  `,
  styles: `
    .backdrop { position: fixed; inset: 0; z-index: 40; background: rgba(15, 23, 42, 0.32); }
    .drawer { position: fixed; top: 0; right: 0; bottom: 0; z-index: 41; display: flex; flex-direction: column;
              width: min(520px, 100%); background: var(--surface); border-left: 1px solid var(--border); box-shadow: var(--shadow-lg); outline: none; }
    header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 18px 20px 14px; border-bottom: 1px solid var(--border); }
    .min { min-width: 0; display: flex; flex-direction: column; align-items: flex-start; gap: 6px; }
    .title { display: flex; align-items: baseline; gap: 8px; } .title h2 { margin: 0; font-size: 18px; }
    .scroll { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px 28px; display: flex; flex-direction: column; gap: 18px; }
    h3 { margin: 0 0 8px; font-size: 13px; font-weight: 600; } h3 .faint { font-weight: 400; }
    .small { font-size: 12px; } .mono { font-family: var(--mono); font-size: 12.5px; }
    .err { padding: 9px 12px; border-radius: var(--radius-sm); background: var(--danger-soft); color: var(--danger); font-size: 12.5px; overflow-wrap: anywhere; }
    .stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid var(--border); border-radius: var(--radius-sm); }
    .stats div { display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; min-width: 0; }
    .stats div + div { border-left: 1px solid var(--border); }
    @media (max-width: 460px) { .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } .stats div:nth-child(3) { border-left: 0; } }
    .k { font-size: 11.5px; color: var(--text-muted); } .v { font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .spark { display: block; width: 100%; height: 64px; overflow: visible; }
    .area { fill: var(--primary-soft); } .line { fill: none; stroke: var(--primary); stroke-width: 2; vector-effect: non-scaling-stroke; }
    .down { fill: var(--danger); }
    .planning { padding: 14px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-2); }
    .axis { display: flex; justify-content: space-between; margin-top: 4px; font-size: 11px; }
    dl { display: grid; grid-template-columns: 92px minmax(0, 1fr); gap: 7px 12px; margin: 0; font-size: 13px; }
    dt { color: var(--text-muted); } dd { margin: 0; overflow-wrap: anywhere; }
    .pill { display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
    .pill .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
    .pill[data-tone='ok'] { color: var(--ok); background: var(--ok-soft); }
    .pill[data-tone='warn'] { color: var(--warn); background: var(--warn-soft); }
    .pill[data-tone='danger'] { color: var(--danger); background: var(--danger-soft); }
    .pill[data-tone='muted'] { color: var(--text-muted); background: var(--surface-2); }
    /* in on insertion; out while the host has animate.leave's class (its own no-op animation keeps it until the end) */
    .backdrop { animation: fade 0.2s ease both; } .drawer { animation: slide 0.28s cubic-bezier(0.2, 0.8, 0.2, 1) both; }
    :host(.leaving) { display: block; animation: hold 0.2s linear both; }
    :host(.leaving) .backdrop { animation: fade 0.2s ease reverse both; } :host(.leaving) .drawer { animation: slide 0.2s ease-in reverse both; }
    @keyframes fade { from { opacity: 0; } }
    @keyframes slide { from { transform: translateX(100%); } }
    @keyframes hold { to { opacity: 1; } }
    @media (prefers-reduced-motion: reduce) { .backdrop, .drawer, :host(.leaving), :host(.leaving) .backdrop, :host(.leaving) .drawer { animation: none; } }
  `,
})
export class AgentDrawer {
  readonly agent = input.required<AgentAdmin>();
  readonly ui = input<Ui | undefined>();
  readonly samples = input<Sample[]>([]);
  readonly busy = input<AgentAdminAction | undefined>();
  readonly act = output<AgentAdminAction>();
  readonly closed = output<void>();
  /** The agent after its planning text was saved or reset. */
  readonly updated = output<AgentAdmin>();

  protected readonly w = W;
  protected readonly h = H;

  constructor() {
    const host = inject<ElementRef<HTMLElement>>(ElementRef);
    afterNextRender(() => host.nativeElement.querySelector<HTMLElement>('.drawer')?.focus());
  }

  protected readonly tone = computed(() => STATUS[this.agent().status]?.tone ?? 'muted');
  protected readonly label = computed(() => STATUS[this.agent().status]?.label ?? this.agent().status);
  protected readonly page = computed(() => `/agents/${this.agent().name.replace(/_/g, '-')}`);

  /** The response-time chart (down checks drawn as red dots at the bottom), the average and the availability. */
  protected readonly chart = computed(() => {
    const samples = this.samples();
    const ms = samples.map((s) => s.ms).filter((v): v is number => v != null);
    const max = Math.max(10, ...ms);
    const step = samples.length > 1 ? W / (samples.length - 1) : 0;
    const points = samples.map((s, i) => ({ x: +(i * step).toFixed(1), y: +(H - 4 - ((s.ms ?? 0) / max) * (H - 12)).toFixed(1), up: s.up }));
    const line = points.map((p) => `${p.x},${p.y}`).join(' ');
    const ups = samples.filter((s) => s.up).length;
    return {
      points,
      line,
      area: points.length ? `M0,${H} L${line.replaceAll(' ', ' L')} L${W},${H} Z` : '',
      max: Math.round(max),
      avg: ms.length ? Math.round(ms.reduce((a, b) => a + b, 0) / ms.length) : null,
      availability: samples.length ? `${Math.round((ups / samples.length) * 100)}%` : null,
      from: samples.length ? agoMs(Date.now() - samples[0].at * 1000) : '',
    };
  });

  protected ago(seconds: number): string {
    return agoMs(Date.now() - seconds * 1000);
  }

  protected studio(url: string): string {
    return `https://smith.langchain.com/studio/?baseUrl=${encodeURIComponent(url)}`;
  }
}
