import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  AgentCard,
  AgentResult,
  DecisionPanel,
  FLOW_ICONS,
  OrchestratorService,
  StatusBadge,
  Step,
  StepResult,
  StepUiStatus,
  ThreadSummary,
  iconForAgent,
  interruptStepId,
  markdownToHtml,
} from '@altasnim/shared';

/** "step s1 (rag) failed verification: <why>" (the supervisor's replan feedback, nodes/progress.py) */
const FEEDBACK_RE = /^step (\S+) \(([^)]+)\) (failed verification|failed|rejected|revise)(?::\s*(.*))?$/s;

interface AgentWork {
  step: Step;
  status: StepUiStatus;
  result: AgentResult | null;
  /** seconds since the steps it waited for finished (step times are whole seconds); null when not known */
  seconds: number | null;
  finishedAt: string | null;
  remoteThread: string | null;
  usedFrom: string[];
  waiting: boolean;
}

interface Rejection {
  agent: string;
  why: string;
  reason: string;
}

/** One run, agent by agent: what each agent was asked, what it used and returned, how long it took. */
@Component({
  selector: 'alt-run-detail',
  imports: [StepResult, StatusBadge, DecisionPanel, RouterLink, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <div class="page-header">
        <div class="min">
          <a routerLink=".." class="small">← All runs</a>
          <h1>{{ thread()?.values?.request || 'Run' }}</h1>
          <p class="muted small">
            {{ thread()?.createdAt | date: 'medium' }}
            @if (took(); as s) { · took {{ s }} }
            · <span class="mono" [title]="threadId()">thread {{ threadId().slice(0, 8) }}</span>
          </p>
        </div>
        <div class="row">
          @if (thread(); as t) { <alt-status-badge [status]="gaveUp() ? 'failed' : t.status" /> }
          <button class="btn btn-sm" (click)="load()">Refresh</button>
        </div>
      </div>

      @if (error(); as err) { <div class="card error">{{ err }}</div> }

      @if (thread(); as t) {
        @if (t.interrupt; as pending) {
          <alt-decision-panel [payload]="pending" [busy]="busy()" (decided)="decide($event)" />
        }

        @if (work().length) {
          <nav class="path" aria-label="Agents of this run">
            @for (w of work(); track w.step.id; let last = $last) {
              <button class="hop" [class.on]="only() === w.step.agent" [attr.data-status]="w.status" (click)="toggle(w.step.agent)">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path [attr.d]="icon(w.step.agent)" /></svg>
                {{ w.step.agent }}
                @if (w.seconds != null) { <span class="faint">{{ secs(w.seconds) }}</span> }
              </button>
              @if (!last) { <span class="arrow" aria-hidden="true">→</span> }
            }
          </nav>
        }

        @for (r of rejections(); track $index) {
          <div class="reject">
            <strong>{{ r.agent }}</strong> {{ r.why }}, so the supervisor tried another way.
            @if (r.reason) { <span class="muted">{{ r.reason }}</span> }
          </div>
        }

        <div class="stack">
          @for (w of shown(); track w.step.id) {
            <article class="card agent" [attr.data-status]="w.status" [class.waiting]="w.waiting">
              <header>
                <span class="icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path [attr.d]="icon(w.step.agent)" /></svg></span>
                <div class="min">
                  <div class="title"><h2>{{ w.step.agent }}</h2>
                    <span class="faint small">step {{ w.step.id }}{{ w.step.added_by === 'policy' ? ' · added by policy' : '' }}</span></div>
                  @if (cards()[w.step.agent]?.description; as d) { <p class="desc">{{ d }}</p> }
                </div>
                <div class="when">
                  <alt-status-badge [status]="w.waiting ? 'waiting_approval' : w.status" />
                  @if (w.finishedAt) {
                    <span class="faint small">{{ w.seconds != null ? secs(w.seconds) + ' · ' : '' }}{{ w.finishedAt | date: 'mediumTime' }}</span>
                  }
                </div>
              </header>

              <dl>
                <dt>Asked</dt><dd>{{ w.step.objective }}</dd>
                @for (p of params(w.step); track p.key) { <dt>{{ p.key }}</dt><dd class="mono">{{ p.value }}</dd> }
                @if (w.usedFrom.length) { <dt>Used</dt><dd>{{ w.usedFrom.join(', ') }}</dd> }
              </dl>

              @if (w.result; as result) {
                <div class="out">
                  <h3>Returned</h3>
                  <alt-step-result [result]="result" [header]="false" />
                  @if (result.error) { <div class="err">{{ result.error }}</div> }
                </div>
              } @else if (w.status === 'running') {
                <p class="faint small">Working…</p>
              } @else if (w.status === 'queued') {
                <p class="faint small">Waiting for {{ w.usedFrom.join(', ') || 'its turn' }}.</p>
              }

              @if (w.remoteThread) { <footer class="faint small mono">agent thread {{ w.remoteThread }}</footer> }
            </article>
          } @empty {
            @if (!work().length) {
              <article class="card agent">
                <header>
                  <span class="icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path [attr.d]="supervisorIcon" /></svg></span>
                  <div class="min"><h2>supervisor</h2><p class="desc">Answered directly: no agent was needed.</p></div>
                </header>
                @if (t.values.final) { <div class="answer" [innerHTML]="finalHtml()"></div> }
              </article>
            }
          }
        </div>

        @if (work().length && t.values.final && !answeredBySynthesizer()) {
          <article class="card agent final">
            <header><div class="min"><h2>Answer</h2><p class="desc">from the supervisor</p></div></header>
            <div class="answer" [innerHTML]="finalHtml()"></div>
          </article>
        }
      }
    </div>
  `,
  styles: `
    .small { font-size: 12px; } .mono { font-family: var(--mono); font-size: 12.5px; } .min { min-width: 0; }
    .page-header h1 { overflow-wrap: anywhere; }
    .error { border-color: var(--danger); color: var(--danger); background: var(--danger-soft); }
    .path { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 14px; }
    .hop { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 12px; font: inherit; font-size: 13px; font-weight: 500;
           color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 999px; cursor: pointer; }
    .hop:hover { border-color: var(--border-strong); } .hop.on { border-color: var(--primary); background: var(--primary-soft); }
    .hop svg, .icon svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
    .hop[data-status='done'] svg { color: var(--ok); } .hop:is([data-status='failed'], [data-status='rejected']) svg { color: var(--danger); }
    .hop[data-status='running'] svg { color: var(--info); }
    .arrow, .faint { color: var(--text-faint); }
    .reject { margin-bottom: 10px; padding: 9px 14px; border-radius: var(--radius-sm); font-size: 13px; background: var(--warn-soft); color: var(--warn); }
    .reject .muted { display: block; margin-top: 2px; }
    .agent { position: relative; overflow: hidden; }
    .agent::before { content: ''; position: absolute; inset: 0 auto 0 0; width: 3px; background: var(--border-strong); }
    .agent[data-status='done']::before { background: var(--ok); } .agent[data-status='running']::before { background: var(--info); }
    .agent:is([data-status='failed'], [data-status='rejected'])::before { background: var(--danger); }
    .agent.waiting::before { background: var(--warn); } .agent.final::before { background: var(--primary); }
    header { display: flex; align-items: flex-start; gap: 12px; }
    .icon { display: grid; place-items: center; flex: none; width: 34px; height: 34px; border-radius: 9px; color: var(--primary); background: var(--primary-soft); }
    .icon svg { width: 18px; height: 18px; }
    .title { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 8px; } h2 { margin: 0; font-size: 15px; }
    .desc { margin: 2px 0 0; font-size: 12.5px; color: var(--text-muted); }
    .when { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; margin-left: auto; white-space: nowrap; }
    dl { display: grid; grid-template-columns: 84px minmax(0, 1fr); gap: 6px 12px; margin: 14px 0 0; font-size: 13px; }
    dt { color: var(--text-muted); } dd { margin: 0; overflow-wrap: anywhere; }
    .out { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); }
    h3 { margin: 0 0 4px; font-size: 12px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-faint); }
    .err { margin-top: 8px; padding: 8px 12px; border-radius: var(--radius-sm); background: var(--danger-soft); color: var(--danger); font-size: 12.5px; }
    footer { margin-top: 10px; overflow-wrap: anywhere; }
    .answer { margin-top: 10px; font-size: 13.5px; line-height: 1.6; } .answer ::ng-deep :is(p, ul, ol) { margin: 0 0 6px; }
    @media (max-width: 560px) { header { flex-wrap: wrap; } .when { align-items: flex-start; margin-left: 46px; } }
  `,
})
export class RunDetail {
  /** Bound from the route param (withComponentInputBinding). */
  readonly threadId = input.required<string>();
  private readonly orchestrator = inject(OrchestratorService);
  protected readonly thread = signal<ThreadSummary | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly cards = signal<Record<string, AgentCard>>({});
  /** show one agent's cards only (clicked in the path) */
  protected readonly only = signal<string | null>(null);
  protected readonly supervisorIcon = FLOW_ICONS.supervisor;

  protected readonly work = computed<AgentWork[]>(() => {
    const t = this.thread();
    const values = t?.values;
    const steps = (values?.plan?.steps ?? []).filter((s) => s.kind === 'agent' || s.kind === 'hitl');
    const status = values?.step_status ?? {};
    const results = values?.results ?? {};
    const waiting = interruptStepId(t?.interrupt);
    const done = (id: string) => (status[id] && status[id].status !== 'queued' && status[id].status !== 'running' ? status[id].updated_at : null);
    const agentOf = (id: string) => steps.find((s) => s.id === id)?.agent ?? id;
    // a first step started with the run; after a replan, when the new plan started is not recorded
    const runStart = values?.replans ? null : t!.createdAt;
    return steps.map((step) => {
      const finishedAt = done(step.id);
      const startedAt = step.depends_on.length ? step.depends_on.map(done) : [runStart];
      const known = startedAt.filter((x): x is string => !!x).map(Date.parse);
      const seconds = finishedAt && known.length ? Math.max(0, (Date.parse(finishedAt) - Math.max(...known)) / 1000) : null;
      return {
        step,
        status: status[step.id]?.status ?? 'queued',
        result: results[step.id] ?? null,
        seconds,
        finishedAt,
        remoteThread: status[step.id]?.remote_thread ?? null,
        usedFrom: step.depends_on.map(agentOf),
        waiting: waiting === step.id,
      };
    });
  });

  protected readonly shown = computed(() => this.work().filter((w) => !this.only() || w.step.agent === this.only()));

  /** Why the supervisor replanned. A rejection by the verifier is shown once: on the agent it rejected. */
  protected readonly rejections = computed<Rejection[]>(() => {
    const all = (this.thread()?.values.feedback ?? []).flatMap((line) => {
      const m = FEEDBACK_RE.exec(line);
      const reason = (m?.[4] ?? '').replace(/^Verification failed:\s*(\S+:\s*)?/, '').trim();
      return m ? [{ agent: m[2], why: m[3] === 'revise' ? 'was asked to revise' : m[3], reason }] : [];
    });
    const verified = all.some((r) => r.why === 'failed verification');
    return all.filter((r) => !(verified && r.agent === 'verifier' && r.why === 'failed'));
  });

  protected readonly answeredBySynthesizer = computed(() =>
    this.work().some((w) => w.step.agent === 'synthesizer' && w.result?.status === 'ok'),
  );
  protected readonly gaveUp = computed(() => /^(I could not|Stopped:|Plan is stuck)/.test(this.thread()?.values.final ?? ''));
  protected readonly finalHtml = computed(() => markdownToHtml(this.thread()?.values.final ?? ''));

  protected readonly took = computed(() => {
    const t = this.thread();
    if (!t || t.status === 'busy') return null;
    return this.secs((Date.parse(t.updatedAt) - Date.parse(t.createdAt)) / 1000);
  });

  constructor() {
    this.orchestrator.agentCards().then((cards) => this.cards.set(cards));
    effect(() => {
      this.threadId();
      this.only.set(null);
      this.load();
    });
  }

  protected async load(): Promise<void> {
    this.error.set(null);
    try {
      this.thread.set(await this.orchestrator.thread(this.threadId()));
    } catch (err) {
      this.error.set(`Could not load run: ${err instanceof Error ? err.message : err}`);
    }
  }

  protected async decide(decision: unknown): Promise<void> {
    this.busy.set(true);
    try {
      this.thread.set(await this.orchestrator.resume(this.threadId(), decision));
    } catch (err) {
      this.error.set(`Could not resume: ${err instanceof Error ? err.message : err}`);
    } finally {
      this.busy.set(false);
    }
  }

  protected toggle(agent: string): void {
    this.only.update((current) => (current === agent ? null : agent));
  }

  protected icon(agent: string): string {
    return FLOW_ICONS[iconForAgent(agent)];
  }

  /** The step's inputs, e.g. question = "what is a pegging sheet". */
  protected params(step: Step): { key: string; value: string }[] {
    return Object.entries(step.params ?? {}).map(([key, value]) => ({
      key,
      value: typeof value === 'string' ? value : JSON.stringify(value),
    }));
  }

  protected secs(s: number): string {
    if (s < 1) return '< 1 s';
    return s < 60 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
  }
}
