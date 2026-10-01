import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import {
  AgentResult,
  CurrentRun,
  DecisionPanel,
  FLOW_ICONS,
  FlowPhase,
  OrchestratorService,
  RunEvent,
  describeEvent,
  iconForAgent,
} from '@altasnim/shared';

import { ActivityTimeline, TimelineItem } from './activity-timeline';
import { AgentStage } from './agent-stage';
import { StepList, StepRow } from './step-list';

/** Extra line icons for the activity timeline (FLOW_ICONS has the agents'). */
const EVENT_ICONS = {
  plan: 'M8 6h13 M8 12h13 M8 18h13 M3 6h.01 M3 12h.01 M3 18h.01',
  start: 'M7 4.5v15l12-7.5z',
  check: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M8.5 12.5l2.5 2.5 5-5',
  cross: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M15 9l-6 6 M9 9l6 6',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2',
  dot: 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
  loop: 'M3 12a9 9 0 1 0 3-6.7L3 8 M3 3v5h5',
} as const;

const PHASE: Record<FlowPhase, { label: string; tone: string }> = {
  idle: { label: 'Ready', tone: 'muted' },
  running: { label: 'Running', tone: 'info' },
  interrupted: { label: 'Waiting for you', tone: 'warn' },
  done: { label: 'Completed', tone: 'ok' },
  error: { label: 'Failed', tone: 'danger' },
};

function seconds(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
  const s = ms / 1000;
  return s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

const timeOf = (e: RunEvent) => (e.at ? Date.parse(e.at) : NaN);

/**
 * Multi Agent Flow: the live flow of the conversation in the Assistant: the agent stage (the supervisor picks
 * and runs the agents), the steps and the live activity. It draws the shared CurrentRun.
 */
@Component({
  selector: 'alt-flow-page',
  imports: [AgentStage, DecisionPanel, ActivityTimeline, StepList],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './flow-page.html',
  styleUrl: './flow-page.css',
})
export class FlowPage {
  private readonly orchestrator = inject(OrchestratorService);
  protected readonly current = inject(CurrentRun);
  protected readonly agentNames = signal<string[]>([]);

  protected readonly session = computed(() => this.current.session());
  protected readonly running = computed(() => this.session().status() === 'running');
  protected readonly phase = computed<FlowPhase>(() => this.session().status());
  protected readonly phaseInfo = computed(() => PHASE[this.phase()]);
  protected readonly values = computed(() => this.session().values());
  protected readonly total = computed(() => this.values().plan?.steps.length ?? 0);

  /** step id -> how long it took (from the live events) */
  protected readonly durations = computed(() => {
    const started = new Map<string, number>();
    const out: Record<string, string> = {};
    for (const e of this.session().events()) {
      const id = String(e['step_id'] ?? '');
      if (e.type === 'step_started') started.set(id, timeOf(e));
      const start = started.get(id);
      if (e.type === 'step_finished' && start !== undefined && !Number.isNaN(start + timeOf(e))) {
        out[id] = seconds(timeOf(e) - start);
      }
    }
    return out;
  });
  protected readonly stepRows = computed<StepRow[]>(() => {
    const all = this.values().results ?? {};
    return (this.values().plan?.steps ?? [])
      .filter((s) => all[s.id] && all[s.id].status !== 'pending')
      .map((s) => ({
        id: s.id,
        agent: s.agent,
        objective: s.objective,
        result: all[s.id] as AgentResult,
        icon: iconForAgent(s.agent),
        duration: this.durations()[s.id] ?? null,
      }));
  });
  /** The live events; a supervisor decision right after a failure is the loop back (a replan). */
  protected readonly timeline = computed<TimelineItem[]>(() => {
    let failedSince = false;
    return this.session()
      .events()
      .map((e) => {
        const at = e.at?.slice(11, 19) ?? '';
        if (e.type === 'step_finished' && e['status'] !== 'ok') failedSince = true;
        if (e.type === 'supervisor_decision' && failedSince) {
          failedSince = false;
          return { at, text: `Rejected, so the supervisor replans: ${e['reasoning'] ?? ''}`, tone: 'warn', icon: EVENT_ICONS.loop };
        }
        return { at, text: describeEvent(e), ...this.look(e) };
      });
  });

  constructor() {
    this.orchestrator.agentCards().then((cards) => this.agentNames.set(Object.keys(cards)));
  }

  protected async decide(decision: unknown): Promise<void> {
    await this.session().resume(decision);
  }

  /** The tone and icon of one activity event. */
  private look(e: RunEvent): Pick<TimelineItem, 'tone' | 'icon'> {
    switch (e.type) {
      case 'supervisor_decision':
        return { tone: 'primary', icon: FLOW_ICONS.supervisor };
      case 'plan':
        return { tone: 'primary', icon: EVENT_ICONS.plan };
      case 'step_started':
        return { tone: 'info', icon: EVENT_ICONS.start };
      case 'step_finished':
        return e['status'] === 'ok' ? { tone: 'ok', icon: EVENT_ICONS.check } : { tone: 'danger', icon: EVENT_ICONS.cross };
      case 'step_waiting_approval':
        return { tone: 'warn', icon: EVENT_ICONS.clock };
      case 'final':
        return { tone: 'ok', icon: FLOW_ICONS.output };
      default:
        return { tone: 'muted', icon: EVENT_ICONS.dot };
    }
  }
}
