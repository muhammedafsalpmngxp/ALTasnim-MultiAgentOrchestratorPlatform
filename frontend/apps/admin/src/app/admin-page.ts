import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import {
  AgentAdmin,
  AgentAdminAction,
  AuditEntry,
  ORCHESTRATOR_API,
  OrchestratorService,
  PlatformAdmin,
  PlatformPolicies,
  ThreadSummary,
} from '@altasnim/shared';

import { AgentsTab } from './agents-tab';
import { AuditTab } from './audit-tab';
import { OverviewTab } from './overview-tab';
import { PoliciesTab } from './policies-tab';
import { Sample, Ui, agoMs, answers, isUp, portOf, remember, remembered } from './admin-utils';

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'agents', label: 'Agents' },
  { id: 'policies', label: 'Policies' },
  { id: 'audit', label: 'Audit log' },
] as const;
type TabId = (typeof TABS)[number]['id'];

const AUTO_REFRESH_MS = 20_000;
const HISTORY = 40;
const AUTO_KEY = 'altasnim.admin.auto';

/**
 * The platform's admin console. Overview (health, runs, agent usage), Agents (every agent of the supervisor with
 * its backend and UI, re-check / pause / resume, a details drawer), Policies (changed at runtime) and the audit
 * log of every admin action. The tab and the open agent are in the URL (?tab=agents&agent=rag): links can be shared.
 */
@Component({
  selector: 'alt-admin-page',
  imports: [RouterLink, OverviewTab, AgentsTab, PoliciesTab, AuditTab],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <header class="page-header">
        <div>
          <div class="eyebrow">Administration</div>
          <h1>Admin console</h1>
          <p>Agents, policies and the audit trail of the multi-agent platform.</p>
        </div>
        <div class="actions">
          <span class="sync" [class.bad]="!!error()" [title]="loadedAt() ? 'Last loaded ' + clock(loadedAt()!) : ''">
            <span class="dot" [class.busy]="loading()"></span>
            {{ loading() && !loadedAt() ? 'Loading…' : error() ? 'Supervisor unreachable' : 'Updated ' + ago(loadedAt()) }}
          </span>
          <label class="switch" title="Refresh every 20 s">
            <input type="checkbox" [checked]="auto()" (change)="setAuto($any($event.target).checked)" />
            <span class="track"></span>Auto-refresh
          </label>
          <button class="btn btn-sm" [disabled]="!platform()" (click)="exportJson()" title="Download agents, policies and audit log as JSON">
            Export
          </button>
          <button class="btn btn-sm btn-primary" [disabled]="loading()" (click)="load()">
            {{ loading() ? 'Refreshing…' : 'Refresh' }}
          </button>
        </div>
      </header>

      @if (error(); as err) {
        <div class="alert" role="alert">
          <strong>Could not load from the supervisor.</strong> <span>{{ err }}</span>
          <button class="btn btn-ghost btn-sm" (click)="error.set(null)" aria-label="Dismiss">✕</button>
        </div>
      }

      <nav class="tabs" role="tablist" aria-label="Admin sections">
        @for (t of tabs; track t.id) {
          <a role="tab" [routerLink]="[]" [queryParams]="{ tab: t.id }" [class.active]="tab() === t.id"
             [attr.aria-selected]="tab() === t.id">
            {{ t.label }}
            @if (t.id === 'agents' && attention()) {
              <span class="n danger" [title]="attention() + ' agent(s) down'">{{ attention() }}</span>
            } @else if (t.id === 'audit' && audit().length) {
              <span class="n">{{ audit().length }}</span>
            }
          </a>
        }
      </nav>

      <div class="body">
        @switch (tab()) {
          @case ('overview') {
            <alt-admin-overview [platform]="platform()" [runs]="runs()" [approvals]="approvals()" [uis]="uis()"
                                [audit]="audit()" (openAgent)="openAgent($event)" />
          }
          @case ('agents') {
            <alt-admin-agents [platform]="platform()" [uis]="uis()" [busy]="busy()" [history]="history()"
                              [selected]="selected()" (act)="act($event.agent, $event.action)" (recheckAll)="recheckAll()"
                              (select)="openAgent($event)" (updated)="customised($event)" />
          }
          @case ('policies') {
            <alt-admin-policies [policies]="policies()" (saved)="policiesSaved($event)" />
          }
          @case ('audit') {
            <alt-admin-audit [entries]="audit()" />
          }
        }
      </div>
    </div>
  `,
  styles: `
    .eyebrow { font-size: 11.5px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--primary); margin-bottom: 4px; }
    .page-header { flex-wrap: wrap; }
    .actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
    .sync { display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--text-muted); white-space: nowrap; }
    .sync .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 3px var(--ok-soft); }
    .sync .dot.busy { background: var(--info); box-shadow: 0 0 0 3px var(--info-soft); animation: pulse 1s ease-in-out infinite; }
    .sync.bad .dot { background: var(--danger); box-shadow: 0 0 0 3px var(--danger-soft); }
    @keyframes pulse { 50% { opacity: 0.35; } }
    .switch { display: inline-flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-muted); cursor: pointer; user-select: none; }
    .switch input { position: absolute; opacity: 0; pointer-events: none; }
    .track { position: relative; width: 30px; height: 17px; border-radius: 999px; background: var(--border-strong); transition: background 0.2s; }
    .track::after { content: ''; position: absolute; top: 2px; left: 2px; width: 13px; height: 13px; border-radius: 50%;
                    background: #fff; box-shadow: var(--shadow-sm); transition: transform 0.2s; }
    .switch input:checked + .track { background: var(--primary); }
    .switch input:checked + .track::after { transform: translateX(13px); }
    .switch input:focus-visible + .track { outline: 2px solid var(--focus); outline-offset: 2px; }
    .alert { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 10px; margin-bottom: 16px; padding: 10px 14px;
             border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent); border-radius: var(--radius-sm);
             background: var(--danger-soft); color: var(--danger); font-size: 13px; }
    .alert span { flex: 1; min-width: 0; overflow-wrap: anywhere; }
    .tabs { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid var(--border); overflow-x: auto; scrollbar-width: none; }
    .tabs a { position: relative; display: inline-flex; align-items: center; gap: 7px; padding: 10px 14px; font-weight: 500;
              color: var(--text-muted); white-space: nowrap; text-decoration: none; transition: color 0.15s; }
    .tabs a:hover { color: var(--text); }
    .tabs a::after { content: ''; position: absolute; left: 10px; right: 10px; bottom: -1px; height: 2px; border-radius: 2px;
                     background: var(--primary); transform: scaleX(0); transition: transform 0.2s ease; }
    .tabs a.active { color: var(--text); }
    .tabs a.active::after { transform: scaleX(1); }
    .n { min-width: 18px; padding: 0 6px; border-radius: 999px; font-size: 11px; font-weight: 600; line-height: 18px; text-align: center;
         background: var(--surface-3); color: var(--text-muted); }
    .n.danger { background: var(--danger-soft); color: var(--danger); }
    /* opacity only: a transform would make .body the containing block of the agent drawer (position: fixed) */
    .body { animation: fade 0.25s ease both; }
    @keyframes fade { from { opacity: 0; } }
    @media (prefers-reduced-motion: reduce) { .body, .sync .dot.busy { animation: none; } }
  `,
})
export class AdminPage {
  private readonly orchestrator = inject(OrchestratorService);
  private readonly apiUrl = inject(ORCHESTRATOR_API);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly query = toSignal(this.route.queryParamMap.pipe(map((q) => ({ tab: q.get('tab'), agent: q.get('agent') }))));

  protected readonly tabs = TABS;
  protected readonly tab = computed<TabId>(() => TABS.find((t) => t.id === this.query()?.tab)?.id ?? 'overview');
  protected readonly selected = computed(() => this.query()?.agent ?? null);

  protected readonly platform = signal<PlatformAdmin | null>(null);
  protected readonly policies = signal<PlatformPolicies | null>(null);
  protected readonly audit = signal<AuditEntry[]>([]);
  protected readonly runs = signal<ThreadSummary[] | null>(null);
  protected readonly approvals = signal<number | null>(null);
  protected readonly uis = signal<Record<string, Ui>>({});
  /** Every check of each agent this session (latency and whether it answered): the drawer's chart and availability. */
  protected readonly history = signal<Record<string, Sample[]>>({});
  protected readonly busy = signal<Record<string, AgentAdminAction | undefined>>({});
  protected readonly error = signal<string | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadedAt = signal<number | null>(null);
  protected readonly auto = signal(remembered(AUTO_KEY) !== 'off');
  private readonly now = signal(Date.now());

  protected readonly attention = computed(
    () => (this.platform()?.agents ?? []).filter((a) => a.status === 'down' || a.status === 'not_found').length,
  );

  constructor() {
    void this.load();
    const clock = setInterval(() => this.now.set(Date.now()), 1000);
    const refresh = setInterval(() => this.auto() && !document.hidden && void this.load(true), AUTO_REFRESH_MS);
    inject(DestroyRef).onDestroy(() => {
      clearInterval(clock);
      clearInterval(refresh);
    });
  }

  /** ``quiet``: the automatic refresh (the button does not change). */
  protected async load(quiet = false): Promise<void> {
    if (!quiet) this.loading.set(true);
    const o = this.orchestrator;
    const [platform, policies, audit, runs, approvals] = await Promise.allSettled([
      o.adminAgents(), o.policies(), o.adminAudit(), o.threads(50), o.pendingApprovals(),
    ]);
    if (platform.status === 'fulfilled') {
      this.platform.set(platform.value);
      this.record(platform.value.agents);
      this.error.set(null);
      this.loadedAt.set(Date.now());
    } else {
      this.error.set(String(platform.reason instanceof Error ? platform.reason.message : platform.reason));
    }
    if (policies.status === 'fulfilled') this.policies.set(policies.value as unknown as PlatformPolicies);
    if (audit.status === 'fulfilled') this.audit.set(audit.value);
    if (runs.status === 'fulfilled') this.runs.set(runs.value);
    if (approvals.status === 'fulfilled') this.approvals.set(approvals.value.length);
    this.loading.set(false);
    void this.loadUis();
  }

  protected async act(name: string, action: AgentAdminAction): Promise<void> {
    this.busy.update((b) => ({ ...b, [name]: action }));
    try {
      this.merge(await this.orchestrator.adminAction(name, action));
    } catch (err) {
      this.error.set(`${action} ${name}: ${err instanceof Error ? err.message : err}`);
    } finally {
      this.busy.update((b) => ({ ...b, [name]: undefined }));
    }
    void this.orchestrator.adminAudit().then((a) => this.audit.set(a), () => undefined);
  }

  /** Every node, at once (each is one network search + card fetch). */
  protected async recheckAll(): Promise<void> {
    const nodes = (this.platform()?.agents ?? []).filter((a) => a.node && !this.busy()[a.name]);
    await Promise.all(nodes.map((a) => this.act(a.name, 'recheck')));
  }

  protected openAgent(name: string | null): void {
    void this.router.navigate([], { relativeTo: this.route, queryParams: { tab: 'agents', agent: name } });
  }

  protected customised(agent: AgentAdmin): void {
    this.merge(agent);
    void this.orchestrator.adminAudit().then((a) => this.audit.set(a), () => undefined);
  }

  protected policiesSaved(policies: PlatformPolicies): void {
    this.policies.set(policies);
    void this.orchestrator.adminAudit().then((a) => this.audit.set(a), () => undefined);
  }

  protected setAuto(on: boolean): void {
    this.auto.set(on);
    remember(AUTO_KEY, on ? 'on' : 'off');
  }

  /** Agents, their UIs, the policies and the audit log as one JSON file (for a ticket or a hand-over). */
  protected exportJson(): void {
    const snapshot = {
      exported_at: new Date().toISOString(),
      supervisor_api: this.apiUrl,
      platform: this.platform(),
      uis: this.uis(),
      policies: this.policies(),
      audit: this.audit(),
    };
    const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' }));
    const a = Object.assign(document.createElement('a'), {
      href: url,
      download: `altasnim-admin-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`,
    });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  protected ago(at: number | null): string {
    return at ? agoMs(this.now() - at) : '—';
  }

  protected clock(at: number): string {
    return new Date(at).toLocaleTimeString();
  }

  private merge(updated: AgentAdmin): void {
    this.platform.update((p) => p && { ...p, agents: p.agents.map((a) => (a.name === updated.name ? { ...a, ...updated } : a)) });
    this.record([updated]);
  }

  /** One sample per check (the supervisor checks each agent at most every 60 s: a refresh may bring the same one). */
  private record(agents: AgentAdmin[]): void {
    this.history.update((history) => {
      const next = { ...history };
      for (const a of agents) {
        if (!a.node || a.checked_at == null) continue;
        const samples = next[a.name] ?? [];
        if (samples.at(-1)?.at === a.checked_at) continue;
        next[a.name] = [...samples, { at: a.checked_at, ms: a.latency_ms, up: isUp(a.status) }].slice(-HISTORY);
      }
      return next;
    });
  }

  /** The micro-frontends from the shell's federation manifest, each checked for its dev server. */
  private async loadUis(): Promise<void> {
    let manifest: Record<string, string> = {};
    try {
      const res = await fetch(`${location.origin}/federation.manifest.json`, { cache: 'no-store' });
      if (res.ok) manifest = await res.json();
    } catch {
      return; // admin running on its own port: no manifest
    }
    const known = this.uis();
    const entries = Object.entries(manifest);
    this.uis.set(Object.fromEntries(entries.map(([name, url]) => [name, { name, url, port: portOf(url), up: known[name]?.up ?? null }])));
    const checked = await Promise.all(entries.map(async ([name, url]) => [name, { name, url, port: portOf(url), up: await answers(url) }] as const));
    this.uis.set(Object.fromEntries(checked));
  }
}
