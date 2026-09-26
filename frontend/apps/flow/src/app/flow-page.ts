import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import {
  AgentCard,
  AgentResult,
  DecisionPanel,
  FlowDiagram,
  FlowPhase,
  interruptStepId,
  OrchestratorService,
  RunEvent,
  StatusBadge,
  StepResult,
} from '@altasnim/shared';

const EXAMPLES = [
  'What is the price of iPhone?',
  'check the price of iphone then share the mail to rijin@gmail.com',
  'Compare iPhone price in Oman and UAE and email it to rijin@gmail.com',
  'check the iPhone price and email it',
];

const EVENT_LABELS: Record<string, (e: RunEvent) => string> = {
  supervisor_decision: (e) => `Supervisor decided: ${e['action']}. ${e['reasoning'] ?? ''}`,
  plan: () => 'Plan created and checked by policy',
  step_started: (e) => `${e['step_id']} · ${e['agent']} started`,
  step_finished: (e) => `${e['step_id']} · ${e['agent']} finished (${e['status']})`,
  step_waiting_approval: (e) => `${e['step_id']} · ${e['agent']} is waiting for approval`,
  progress: (e) => `${e['agent']}: ${e['message']}`,
  final: () => 'Answer ready',
};

@Component({
  selector: 'alt-flow-page',
  imports: [FlowDiagram, StepResult, DecisionPanel, StatusBadge],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './flow-page.html',
  styleUrl: './flow-page.css',
})
export class FlowPage {
  private readonly orchestrator = inject(OrchestratorService);
  protected session = this.orchestrator.newSession();
  protected readonly examples = EXAMPLES;
  protected readonly draft = signal('');
  protected readonly cards = signal<Record<string, AgentCard>>({});

  protected readonly running = computed(() => this.session.status() === 'running');
  protected readonly phase = computed<FlowPhase>(() => this.session.status());
  protected readonly values = computed(() => this.session.values());
  protected readonly messages = computed(() => this.values().messages ?? []);
  protected readonly waitingStepId = computed(() => interruptStepId(this.session.interrupt()));
  protected readonly results = computed<AgentResult[]>(() => {
    const v = this.values();
    const all = v.results ?? {};
    return (v.plan?.steps ?? []).map((s) => all[s.id]).filter((r): r is AgentResult => !!r);
  });
  protected readonly timeline = computed(() =>
    this.session.events().map((e) => ({ at: e.at?.slice(11, 19) ?? '', text: (EVENT_LABELS[e.type] ?? (() => e.type))(e) })),
  );

  constructor() {
    this.orchestrator.agentCards().then((cards) => this.cards.set(cards));
  }

  protected async send(text = this.draft()): Promise<void> {
    const request = text.trim();
    if (!request || this.running() || this.session.interrupt()) return;
    this.draft.set('');
    await this.session.ask(request);
  }

  protected async decide(decision: unknown): Promise<void> {
    await this.session.resume(decision);
  }

  protected newFlow(): void {
    this.session = this.orchestrator.newSession();
    this.draft.set('');
  }
}
