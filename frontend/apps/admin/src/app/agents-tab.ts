import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { AgentAdmin, AgentAdminAction, AgentAdminStatus, PlatformAdmin, agentRemoteName } from '@altasnim/shared';

import { AgentDrawer } from './agent-drawer';
import { STATUS, Sample, Ui, isUp } from './admin-utils';

type Filter = 'all' | 'online' | 'attention' | 'paused' | 'off';

const FILTERS: { id: Filter; label: string; match: (s: AgentAdminStatus) => boolean }[] = [
  { id: 'all', label: 'All', match: () => true },
  { id: 'online', label: 'Online', match: isUp },
  { id: 'attention', label: 'Needs attention', match: (s) => s === 'down' || s === 'not_found' },
  { id: 'paused', label: 'Paused', match: (s) => s === 'paused' },
  { id: 'off', label: 'Not a node', match: (s) => s === 'disabled' },
];

/** Every agent of the supervisor: backend (port, graph, machine), UI, status; search, filters, actions, details drawer. */
@Component({
  selector: 'alt-admin-agents',
  imports: [AgentDrawer],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="toolbar">
      <input class="input search" type="search" placeholder="Search agents, ports, machines…" aria-label="Search agents"
             [value]="query()" (input)="query.set($any($event.target).value)" />
      <div class="chips" role="group" aria-label="Filter by status">
        @for (f of filters; track f.id) {
          <button class="chip" [class.on]="filter() === f.id" (click)="filter.set(f.id)" [attr.aria-pressed]="filter() === f.id">
            {{ f.label }}<span>{{ counts()[f.id] }}</span>
          </button>
        }
      </div>
      <button class="btn btn-sm" [disabled]="!platform() || anyBusy()" (click)="recheckAll.emit()"
              title="Search the network for every agent again">{{ anyBusy() ? 'Checking…' : 'Re-check all' }}</button>
    </div>

    @if (platform(); as p) {
      <p class="meta muted small">
        Supervisor <span class="mono">:{{ p.supervisor.port }}</span> · transport {{ p.transport }} · searching
        <span class="mono">{{ p.subnet ?? 'its own /24' }}</span> for each agent's port and graph
      </p>
    }

    <div class="card flush list">
      <div class="list-head"><span>Agent</span><span>Status</span><span>Backend</span><span>Frontend</span><span class="right">Actions</span></div>
      @for (a of shown(); track a.name) {
        @let ui = uiOf(a.name);
        <div class="agent" [class.off]="!a.node" [class.sel]="a.name === selected()" (click)="select.emit(a.name)"
             tabindex="0" (keydown.enter)="select.emit(a.name)" role="button" [attr.aria-label]="'Details of ' + a.name">
          <div class="c-agent">
            <span class="avatar" [attr.data-tone]="tone(a.status)">{{ a.name.slice(0, 2) }}</span>
            <div class="min">
              <div class="name"><strong>{{ a.name }}</strong>@if (a.card?.version) {<span class="faint small">v{{ a.card!.version }}</span>}
                @if (hasOverrides(a)) {<span class="tag" title="Planning text customised in the admin console">customised</span>}</div>
              <div class="muted small ellipsis">{{ a.card?.description ?? (a.node ? 'card not loaded' : 'not a node of the supervisor') }}</div>
            </div>
          </div>
          <div class="c-status">
            <span class="pill" [attr.data-tone]="tone(a.status)"><span class="dot"></span>{{ label(a.status) }}</span>
            @if (a.latency_ms != null && a.status === 'up') { <span class="faint small">{{ a.latency_ms }} ms</span> }
          </div>
          <div class="c-backend min">
            <div class="mono">:{{ a.port ?? '—' }} · {{ a.graph_id ?? '—' }}</div>
            <div class="faint small mono ellipsis">{{ a.url ?? (a.status === 'in_process' ? 'in the supervisor process' : 'no machine found') }}</div>
          </div>
          <div class="c-frontend min">
            @if (ui) {
              <div class="mono">{{ ui.name }} :{{ ui.port }}</div>
              <div class="small" [class]="ui.up === null ? 'faint' : ui.up ? 'ok' : 'danger'">
                {{ ui.up === null ? 'checking…' : ui.up ? 'UI up' : 'UI down' }}
              </div>
            } @else {
              <span class="faint small">no UI</span>
            }
          </div>
          <div class="c-actions" (click)="$event.stopPropagation()" (keydown.enter)="$event.stopPropagation()">
            @if (a.node) {
              <button class="btn btn-sm" [disabled]="!!busy()[a.name]" (click)="act.emit({ agent: a.name, action: 'recheck' })"
                      title="Search the network for it again and fetch its card">{{ busy()[a.name] === 'recheck' ? 'Checking…' : 'Re-check' }}</button>
              @if (a.paused) {
                <button class="btn btn-sm btn-primary" [disabled]="!!busy()[a.name]" (click)="act.emit({ agent: a.name, action: 'resume' })"
                        title="Plan with it again">Resume</button>
              } @else {
                <button class="btn btn-sm" [disabled]="!!busy()[a.name]" (click)="act.emit({ agent: a.name, action: 'pause' })"
                        title="Leave it out of planning (it keeps running)">Pause</button>
              }
            } @else {
              <span class="faint small">enable in agents.dev.yaml</span>
            }
          </div>
        </div>
      } @empty {
        <div class="none">
          @if (platform()) { No agent matches “{{ query() }}”{{ filter() === 'all' ? '' : ' in this filter' }}. }
          @else { Loading agents… }
        </div>
      }
    </div>

    @if (current(); as a) {
      <alt-agent-drawer animate.leave="leaving" [agent]="a" [ui]="uiOf(a.name)" [samples]="history()[a.name] ?? []" [busy]="busy()[a.name]"
                        (act)="act.emit({ agent: a.name, action: $event })" (closed)="select.emit(null)"
                        (updated)="updated.emit($event)" />
    }
  `,
  styles: `
    :host { display: block; }
    .small { font-size: 12px; } .mono { font-family: var(--mono); font-size: 12.5px; }
    .ok { color: var(--ok); } .danger { color: var(--danger); }
    .min { min-width: 0; } .ellipsis { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 12px; }
    .search { flex: 1 1 240px; max-width: 360px; height: 34px; }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; }
    .chip { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 12px; font: inherit; font-size: 12.5px;
            color: var(--text-muted); background: var(--surface); border: 1px solid var(--border); border-radius: 999px; cursor: pointer; }
    .chip span { font-size: 11px; color: var(--text-faint); font-variant-numeric: tabular-nums; }
    .chip:hover { border-color: var(--border-strong); color: var(--text); }
    .chip.on { color: var(--primary); background: var(--primary-soft); border-color: transparent; font-weight: 500; }
    .chip.on span { color: inherit; }
    .toolbar .btn { margin-left: auto; }
    .meta { margin: 0 0 12px; }
    .flush { padding: 0; overflow: hidden; }
    .list { container-type: inline-size; }
    .list-head, .agent { display: grid; gap: 14px; padding: 12px 16px; align-items: center;
      grid-template-columns: minmax(0, 1.6fr) 112px minmax(0, 1.3fr) minmax(0, 1fr) 176px; }
    .list-head { padding-block: 9px; font-size: 11.5px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase;
                 color: var(--text-faint); background: var(--surface-2); border-bottom: 1px solid var(--border); }
    .right { text-align: right; }
    .agent { position: relative; border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.15s; }
    .agent:last-child { border-bottom: 0; }
    .agent:hover { background: var(--surface-2); }
    .agent.sel { background: var(--primary-soft); }
    .agent.sel::before { content: ''; position: absolute; inset: 0 auto 0 0; width: 3px; background: var(--primary); }
    .agent:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
    .agent.off > div { opacity: 0.6; }
    .c-agent { display: flex; align-items: center; gap: 12px; min-width: 0; }
    .avatar { display: grid; place-items: center; flex: none; width: 34px; height: 34px; border-radius: 9px; font-size: 12px;
              font-weight: 700; text-transform: uppercase; color: var(--text-muted); background: var(--surface-3); }
    .avatar[data-tone='ok'] { color: var(--primary); background: var(--primary-soft); }
    .avatar[data-tone='danger'] { color: var(--danger); background: var(--danger-soft); }
    .avatar[data-tone='warn'] { color: var(--warn); background: var(--warn-soft); }
    .name { display: flex; align-items: baseline; gap: 6px; }
    .tag { padding: 0 7px; border-radius: 999px; font-size: 11px; font-weight: 600; background: var(--warn-soft); color: var(--warn); }
    .c-status { display: flex; flex-direction: column; align-items: flex-start; gap: 3px; }
    .c-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }
    @container (max-width: 820px) {
      .list-head { display: none; }
      .agent { grid-template-columns: minmax(0, 1fr) auto; row-gap: 10px; }
      .c-status { grid-column: 2; grid-row: 1; align-items: flex-end; }
      .c-backend, .c-frontend { grid-column: 1 / -1; padding-left: 46px; }
      .c-actions { grid-column: 1 / -1; justify-content: flex-start; padding-left: 46px; }
    }
    .pill { display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; white-space: nowrap; }
    .pill .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
    .pill[data-tone='ok'] { color: var(--ok); background: var(--ok-soft); }
    .pill[data-tone='warn'] { color: var(--warn); background: var(--warn-soft); }
    .pill[data-tone='danger'] { color: var(--danger); background: var(--danger-soft); }
    .pill[data-tone='muted'] { color: var(--text-muted); background: var(--surface-2); }
    .none { padding: 28px 16px; text-align: center; color: var(--text-muted); }
  `,
})
export class AgentsTab {
  readonly platform = input<PlatformAdmin | null>(null);
  readonly uis = input<Record<string, Ui>>({});
  readonly busy = input<Record<string, AgentAdminAction | undefined>>({});
  readonly history = input<Record<string, Sample[]>>({});
  readonly selected = input<string | null>(null);
  readonly act = output<{ agent: string; action: AgentAdminAction }>();
  readonly recheckAll = output<void>();
  readonly select = output<string | null>();
  readonly updated = output<AgentAdmin>();

  protected readonly filters = FILTERS;
  protected readonly query = signal('');
  protected readonly filter = signal<Filter>('all');

  private readonly all = computed(() => this.platform()?.agents ?? []);

  protected readonly counts = computed(
    () => Object.fromEntries(FILTERS.map((f) => [f.id, this.all().filter((a) => f.match(a.status)).length])) as Record<Filter, number>,
  );

  protected readonly shown = computed(() => {
    const q = this.query().trim().toLowerCase();
    const match = FILTERS.find((f) => f.id === this.filter())!.match;
    return this.all().filter((a) => match(a.status) && (!q || this.haystack(a).includes(q)));
  });

  protected readonly current = computed(() => this.all().find((a) => a.name === this.selected()) ?? null);
  protected readonly anyBusy = computed(() => Object.values(this.busy()).some(Boolean));

  protected uiOf(agent: string): Ui | undefined {
    return this.uis()[agentRemoteName(agent)];
  }

  protected label(status: AgentAdminStatus): string {
    return STATUS[status]?.label ?? status;
  }

  protected tone(status: AgentAdminStatus): string {
    return STATUS[status]?.tone ?? 'muted';
  }

  protected hasOverrides(a: AgentAdmin): boolean {
    return Object.keys(a.overrides ?? {}).length > 0;
  }

  private haystack(a: AgentAdmin): string {
    return [a.name, a.port, a.graph_id, a.url, a.card?.description, a.card?.owner, this.label(a.status)].join(' ').toLowerCase();
  }
}
