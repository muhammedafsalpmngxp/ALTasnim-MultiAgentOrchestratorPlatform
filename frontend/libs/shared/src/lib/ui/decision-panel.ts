import { NgComponentOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, Type, computed, effect, inject, input, output, signal } from '@angular/core';

import { AGENT_WIDGET_LOADER } from '../agent-widget';
import { AgentApprovalInterrupt, GateApprovalInterrupt, InterruptPayload } from '../models';
import { JsonView } from './json-view';

/**
 * Answers an orchestrator interrupt:
 * - clarification   -> free-text answer
 * - agent_approval  -> the agent team's approvalForm widget (e.g. edit email), or generic approve/reject
 * - approval (gate) -> approve / revise (with comment) / reject
 */
@Component({
  selector: 'alt-decision-panel',
  imports: [NgComponentOutlet, JsonView],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="panel">
      @switch (payload().kind) {
        @case ('clarification') {
          <h3>The assistant needs more information</h3>
          <p>{{ clarificationQuestion() }}</p>
          <div class="row">
            <input class="input grow" [value]="answer()" (input)="answer.set($any($event.target).value)"
                   (keydown.enter)="sendAnswer()" placeholder="Your answer" [disabled]="busy()" />
            <button class="btn btn-primary" (click)="sendAnswer()" [disabled]="busy() || !answer().trim()">Send</button>
          </div>
        }
        @case ('agent_approval') {
          <h3>Approval needed · {{ agentApproval()?.agent }}</h3>
          <p class="muted">{{ agentApproval()?.objective }}</p>
          @if (agentForm(); as form) {
            <ng-container *ngComponentOutlet="form; inputs: { request: agentApproval()?.request, decide: decideFn }" />
          } @else {
            <alt-json-view [value]="agentApproval()?.request" label="Request from the agent" [open]="true" />
            <div class="row actions">
              <button class="btn btn-primary" (click)="decide({ action: 'approve' })" [disabled]="busy()">Approve</button>
              <button class="btn btn-danger" (click)="decide({ action: 'reject', reason: 'rejected by approver' })"
                      [disabled]="busy()">Reject</button>
            </div>
          }
        }
        @case ('approval') {
          <h3>Approval needed</h3>
          <p>{{ gateApproval()?.objective }}</p>
          <alt-json-view [value]="gateApproval()?.context" label="Context" />
          <input class="input" [value]="comment()" (input)="comment.set($any($event.target).value)"
                 placeholder="Comment (required for revise)" [disabled]="busy()" />
          <div class="row actions">
            <button class="btn btn-primary" (click)="decide({ action: 'approve', comment: comment() })" [disabled]="busy()">
              Approve</button>
            <button class="btn" (click)="decide({ action: 'revise', comment: comment() })"
                    [disabled]="busy() || !comment().trim()">Revise</button>
            <button class="btn btn-danger" (click)="decide({ action: 'reject', comment: comment() })" [disabled]="busy()">
              Reject</button>
          </div>
        }
      }
    </div>
  `,
  styles: `
    .panel { border: 1px solid var(--warn); background: var(--warn-soft); border-radius: var(--radius); padding: 14px 16px; }
    .panel h3 { color: var(--warn); }
    .grow { flex: 1; }
    .actions { margin-top: 10px; }
  `,
})
export class DecisionPanel {
  readonly payload = input.required<InterruptPayload>();
  readonly busy = input(false);
  readonly decided = output<unknown>();

  private readonly loader = inject(AGENT_WIDGET_LOADER, { optional: true });
  protected readonly agentForm = signal<Type<unknown> | null>(null);
  protected readonly answer = signal('');
  protected readonly comment = signal('');

  protected readonly clarificationQuestion = computed(() => {
    const p = this.payload();
    return p.kind === 'clarification' ? p.question : '';
  });
  protected readonly agentApproval = computed(() => {
    const p = this.payload();
    return p.kind === 'agent_approval' ? (p as AgentApprovalInterrupt) : null;
  });
  protected readonly gateApproval = computed(() => {
    const p = this.payload();
    return p.kind === 'approval' ? (p as GateApprovalInterrupt) : null;
  });

  /** Passed to agent approval widgets as the `decide` input. */
  protected readonly decideFn = (decision: unknown) => this.decide(decision);

  constructor() {
    effect(() => {
      const approval = this.agentApproval();
      this.agentForm.set(null);
      if (approval && this.loader) {
        this.loader(approval.agent).then((w) => this.agentForm.set(w?.approvalForm ?? null));
      }
    });
  }

  protected decide(decision: unknown): void {
    this.decided.emit(decision);
  }

  protected sendAnswer(): void {
    const text = this.answer().trim();
    if (text) this.decided.emit(text);
  }
}
