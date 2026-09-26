import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  AgentCard,
  AgentResult,
  FlowDiagram,
  FlowPhase,
  DecisionPanel,
  interruptStepId,
  JsonView,
  OrchestratorService,
  StatusBadge,
  StepResult,
  ThreadSummary,
} from '@altasnim/shared';

@Component({
  selector: 'alt-run-detail',
  imports: [FlowDiagram, StepResult, StatusBadge, DecisionPanel, JsonView, RouterLink, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page stack">
      <div class="page-header">
        <div>
          <a routerLink=".." class="small">← All runs</a>
          <h1>{{ thread()?.values?.request || 'Run' }}</h1>
          <p class="muted small">
            thread {{ threadId() }} · {{ thread()?.createdAt | date: 'medium' }}
          </p>
        </div>
        <div class="row">
          @if (thread(); as t) {
            <alt-status-badge [status]="t.status" />
          }
          <button class="btn btn-sm" (click)="load()">Refresh</button>
        </div>
      </div>

      @if (error(); as err) {
        <div class="card error">{{ err }}</div>
      }

      @if (thread(); as t) {
        @if (t.values.plan) {
          <div class="card canvas">
            <alt-flow-diagram [plan]="t.values.plan" [status]="t.values.step_status ?? {}" [waitingStepId]="waitingStepId()"
                              [cards]="cards()" [request]="t.values.request ?? ''" [phase]="phase()"
                              [final]="t.values.final" [replans]="t.values.replans ?? 0" />
          </div>
        }

        @if (t.interrupt; as pending) {
          <alt-decision-panel [payload]="pending" [busy]="busy()" (decided)="decide($event)" />
        }

        @if (t.values.final) {
          <div class="card">
            <h3>Answer</h3>
            <p class="final">{{ t.values.final }}</p>
          </div>
        }

        @if (results().length) {
          <div class="card">
            <h3>Step results</h3>
            @for (r of results(); track r.step_id) {
              <alt-step-result [result]="r" />
            }
          </div>
        }

        <div class="card">
          <alt-json-view [value]="t.values" label="Full state (threads.get)" />
        </div>
      }
    </div>
  `,
  styles: `
    .small { font-size: 12px; }
    .canvas { padding: 10px; }
    .final { white-space: pre-wrap; margin: 0; }
    .error { border-color: var(--danger); color: var(--danger); background: var(--danger-soft); }
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
  protected readonly phase = computed<FlowPhase>(() => {
    const status = this.thread()?.status;
    return status === 'interrupted' ? 'interrupted' : status === 'busy' ? 'running' : status === 'error' ? 'error' : 'done';
  });

  protected readonly waitingStepId = computed(() => interruptStepId(this.thread()?.interrupt));

  protected readonly results = computed<AgentResult[]>(() => {
    const values = this.thread()?.values;
    const all = values?.results ?? {};
    return (values?.plan?.steps ?? []).map((s) => all[s.id]).filter((r): r is AgentResult => !!r);
  });

  constructor() {
    this.orchestrator.agentCards().then((cards) => this.cards.set(cards));
    effect(() => {
      this.threadId();
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
}
