import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuditEntry, PlatformAdmin, StatusBadge, ThreadSummary } from '@altasnim/shared';

import { STATUS, Ui, agoMs, duration, isUp } from './admin-utils';

/** The supervisor's answer when it gave up (respond node): the run finished but did not answer. */
const GAVE_UP_RE = /^(I could not|Stopped:|Plan is stuck)/;
const PLATFORM_UIS = ['flow', 'runs', 'approvals', 'admin'];

interface Usage {
  agent: string;
  steps: number;
  failed: number;
}

/** Health of the platform at a glance: KPIs over the latest runs, agent usage, recent runs, every service. */
@Component({
  selector: 'alt-admin-overview',
  imports: [RouterLink, StatusBadge],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="kpis">
      <div class="card kpi" [attr.data-tone]="agentsTone()">
        <span class="k">Agents online</span>
        <span class="v">{{ agents().up }}<small>/ {{ agents().nodes }}</small></span>
        <span class="s">
          @if (agents().paused) { {{ agents().paused }} paused · }
          @if (agents().down) { <span class="danger">{{ agents().down }} down</span> } @else { all reachable }
        </span>
      </div>
      <div class="card kpi">
        <span class="k">Runs</span>
        <span class="v">{{ stats().total }}</span>
        <span class="s">{{ stats().running ? stats().running + ' running · ' : '' }}latest {{ stats().total }} conversation{{ stats().total === 1 ? '' : 's' }}</span>
      </div>
      <div class="card kpi" [attr.data-tone]="stats().rate == null ? '' : stats().rate! >= 0.8 ? 'ok' : 'warn'">
        <span class="k">Answered</span>
        <span class="v">{{ stats().rate == null ? '—' : pct(stats().rate!) }}</span>
        <span class="meter"><i [style.width]="pct(stats().rate ?? 0)"></i></span>
      </div>
      <div class="card kpi">
        <span class="k">Avg. run time</span>
        <span class="v">{{ stats().avgMs == null ? '—' : time(stats().avgMs!) }}</span>
        <span class="s">question to answer</span>
      </div>
      <div class="card kpi" [attr.data-tone]="stats().replanned ? 'warn' : ''">
        <span class="k">Replanned</span>
        <span class="v">{{ stats().replanned }}</span>
        <span class="s">runs where a source was rejected</span>
      </div>
      <a class="card kpi link" routerLink="/approvals" [attr.data-tone]="approvals() ? 'warn' : ''">
        <span class="k">Awaiting approval</span>
        <span class="v">{{ approvals() ?? '—' }}</span>
        <span class="s">open the inbox →</span>
      </a>
    </section>

    <section class="grid">
      <div class="card">
        <div class="head"><h2>Agent usage</h2><span class="muted small">steps in the latest runs</span></div>
        @for (u of usage(); track u.agent) {
          <button class="bar" (click)="openAgent.emit(u.agent)" [title]="'Open ' + u.agent">
            <span class="name">{{ u.agent }}</span>
            <span class="track">
              <i class="ok" [style.width.%]="((u.steps - u.failed) / maxSteps()) * 100"></i>
              <i class="bad" [style.width.%]="(u.failed / maxSteps()) * 100"></i>
            </span>
            <span class="num">{{ u.steps }}@if (u.failed) {<span class="danger"> · {{ u.failed }} failed</span>}</span>
          </button>
        } @empty {
          <p class="empty">No runs yet. Ask the Assistant a question to see which agents work on it.</p>
        }
      </div>

      <div class="card">
        <div class="head"><h2>Recent runs</h2><a routerLink="/runs" class="small">All runs →</a></div>
        @for (r of recent(); track r.threadId) {
          <a class="run" [routerLink]="['/runs', r.threadId]">
            <span class="q">{{ r.values.request || '(no question)' }}</span>
            <alt-status-badge [status]="gaveUp(r) ? 'failed' : r.status" />
            <span class="path muted small">{{ path(r) }}</span>
            <span class="faint small">{{ ago(r.updatedAt) }}</span>
          </a>
        } @empty {
          <p class="empty">No runs yet.</p>
        }
      </div>
    </section>

    <section class="card">
      <div class="head"><h2>Services</h2><span class="muted small">backends found on the network · micro-frontends from the manifest</span></div>
      <div class="services">
        <div class="svc"><span class="dot" [class.up]="!!platform()"></span><strong>supervisor</strong>
          <span class="mono muted">:{{ platform()?.supervisor?.port ?? '—' }}</span><span class="faint small">API</span></div>
        @for (a of platform()?.agents ?? []; track a.name) {
          @if (a.node) {
            <button class="svc" (click)="openAgent.emit(a.name)" [title]="label(a.status)">
              <span class="dot" [class.up]="up(a.status)" [class.warn]="a.status === 'paused'"></span><strong>{{ a.name }}</strong>
              <span class="mono muted">:{{ a.port ?? '—' }}</span><span class="faint small">agent</span>
            </button>
          }
        }
        <div class="svc"><span class="dot up"></span><strong>shell</strong><span class="mono muted">:{{ shellPort }}</span><span class="faint small">UI</span></div>
        @for (ui of uiList(); track ui.name) {
          <div class="svc" [title]="ui.url">
            <span class="dot" [class.up]="ui.up === true" [class.wait]="ui.up === null"></span><strong>{{ ui.name }}</strong>
            <span class="mono muted">:{{ ui.port }}</span><span class="faint small">UI</span>
          </div>
        }
      </div>
      @if (audit()[0]; as last) {
        <p class="last small muted">Last admin action: <strong>{{ last.action }}</strong> on {{ last.target }} · {{ ago(last.at) }}</p>
      }
    </section>
  `,
  styles: `
    :host { display: flex; flex-direction: column; gap: 16px; }
    .small { font-size: 12px; } .mono { font-family: var(--mono); font-size: 12px; } .danger { color: var(--danger); }
    .kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(176px, 1fr)); gap: 12px; }
    .kpi { position: relative; display: flex; flex-direction: column; gap: 4px; padding: 16px; overflow: hidden; color: inherit; text-decoration: none; }
    .kpi::before { content: ''; position: absolute; inset: 0 auto 0 0; width: 3px; background: var(--border-strong); }
    .kpi[data-tone='ok']::before { background: var(--ok); } .kpi[data-tone='warn']::before { background: var(--warn); }
    .kpi[data-tone='danger']::before { background: var(--danger); }
    .kpi.link:hover { border-color: var(--border-strong); text-decoration: none; }
    .k { font-size: 12px; font-weight: 500; color: var(--text-muted); }
    .v { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
    .v small { margin-left: 4px; font-size: 14px; font-weight: 500; color: var(--text-faint); }
    .s { font-size: 12px; color: var(--text-faint); }
    .meter { height: 5px; margin-top: 6px; border-radius: 999px; background: var(--surface-3); overflow: hidden; }
    .meter i { display: block; height: 100%; border-radius: inherit; background: var(--ok); transition: width 0.6s ease; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: 16px; }
    .head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
    .head h2 { margin: 0; }
    .bar { display: grid; grid-template-columns: 96px minmax(0, 1fr) auto; align-items: center; gap: 12px; width: 100%; padding: 7px 6px;
           font: inherit; color: inherit; text-align: left; background: none; border: 0; border-radius: var(--radius-sm); cursor: pointer; }
    .bar:hover { background: var(--surface-2); }
    .name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .track { display: flex; height: 8px; border-radius: 999px; background: var(--surface-3); overflow: hidden; }
    .track i { height: 100%; transition: width 0.6s ease; } .track .ok { background: var(--primary); } .track .bad { background: var(--danger); }
    .num { font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .run { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 12px; padding: 9px 6px; color: inherit;
           border-bottom: 1px solid var(--border); text-decoration: none; }
    .run:last-child { border-bottom: 0; }
    .run:hover { background: var(--surface-2); text-decoration: none; }
    .q { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .path { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .empty { margin: 8px 0; color: var(--text-muted); font-size: 13px; }
    .services { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 8px; }
    .svc { display: flex; align-items: center; gap: 8px; min-width: 0; padding: 9px 12px; font: inherit; color: inherit; text-align: left;
           background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm); }
    button.svc { cursor: pointer; } button.svc:hover { border-color: var(--border-strong); background: var(--surface-2); }
    .svc strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
    .svc .faint { margin-left: auto; }
    .dot { flex: none; width: 8px; height: 8px; border-radius: 50%; background: var(--danger); }
    .dot.up { background: var(--ok); } .dot.warn { background: var(--warn); } .dot.wait { background: var(--text-faint); }
    .last { margin: 12px 0 0; }
  `,
})
export class OverviewTab {
  readonly platform = input<PlatformAdmin | null>(null);
  readonly runs = input<ThreadSummary[] | null>(null);
  readonly approvals = input<number | null>(null);
  readonly uis = input<Record<string, Ui>>({});
  readonly audit = input<AuditEntry[]>([]);
  readonly openAgent = output<string>();

  protected readonly shellPort = location.port || '80';

  protected readonly agents = computed(() => {
    const nodes = (this.platform()?.agents ?? []).filter((a) => a.node);
    return {
      nodes: nodes.length,
      up: nodes.filter((a) => isUp(a.status)).length,
      paused: nodes.filter((a) => a.status === 'paused').length,
      down: nodes.filter((a) => a.status === 'down' || a.status === 'not_found').length,
    };
  });

  protected readonly agentsTone = computed(() => {
    const a = this.agents();
    return !this.platform() ? '' : a.down ? 'danger' : a.paused ? 'warn' : 'ok';
  });

  protected readonly stats = computed(() => {
    const runs = this.runs() ?? [];
    const finished = runs.filter((r) => r.status === 'idle' || r.status === 'error');
    const answered = finished.filter((r) => r.status === 'idle' && !!r.values.final && !this.gaveUp(r));
    const times = runs
      .filter((r) => r.status === 'idle' && r.values.final)
      .map((r) => Date.parse(r.updatedAt) - Date.parse(r.createdAt))
      .filter((ms) => ms >= 0 && ms < 3_600_000); // a thread reused hours later is not one run
    return {
      total: runs.length,
      running: runs.filter((r) => r.status === 'busy').length,
      rate: finished.length ? answered.length / finished.length : null,
      avgMs: times.length ? times.reduce((a, b) => a + b, 0) / times.length : null,
      replanned: runs.filter((r) => (r.values.replans ?? 0) > 0).length,
    };
  });

  protected readonly usage = computed<Usage[]>(() => {
    const by = new Map<string, Usage>();
    for (const r of this.runs() ?? []) {
      for (const s of r.values.plan?.steps ?? []) {
        if (s.kind !== 'agent') continue;
        const u = by.get(s.agent) ?? { agent: s.agent, steps: 0, failed: 0 };
        u.steps++;
        const status = r.values.step_status?.[s.id]?.status;
        if (status === 'failed' || status === 'rejected') u.failed++;
        by.set(s.agent, u);
      }
    }
    return [...by.values()].sort((a, b) => b.steps - a.steps);
  });

  protected readonly maxSteps = computed(() => Math.max(1, ...this.usage().map((u) => u.steps)));
  protected readonly recent = computed(() => (this.runs() ?? []).slice(0, 6));

  protected readonly uiList = computed(() => {
    const uis = this.uis();
    return [...PLATFORM_UIS.filter((n) => uis[n]).map((n) => uis[n]), ...Object.values(uis).filter((u) => !PLATFORM_UIS.includes(u.name))];
  });

  protected gaveUp(r: ThreadSummary): boolean {
    return !!r.values.final && GAVE_UP_RE.test(r.values.final);
  }

  /** The agents of the run's (last) plan, in order: "rag → verifier → synthesizer". */
  protected path(r: ThreadSummary): string {
    const steps = (r.values.plan?.steps ?? []).filter((s) => s.kind === 'agent').map((s) => s.agent);
    const replans = r.values.replans ? ` · ${r.values.replans} replan${r.values.replans > 1 ? 's' : ''}` : '';
    return (steps.length ? steps.join(' → ') : 'answered directly') + replans;
  }

  protected ago(iso: string): string {
    return agoMs(Date.now() - Date.parse(iso));
  }

  protected pct(rate: number): string {
    return `${Math.round(rate * 100)}%`;
  }

  protected time(ms: number): string {
    return duration(ms);
  }

  protected up(status: PlatformAdmin['agents'][number]['status']): boolean {
    return isUp(status);
  }

  protected label(status: PlatformAdmin['agents'][number]['status']): string {
    return STATUS[status]?.label ?? status;
  }
}
