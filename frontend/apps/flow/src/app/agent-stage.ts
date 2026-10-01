import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FLOW_ICONS, FlowPhase, Plan, StepStatus, iconForAgent, planWaves } from '@altasnim/shared';

type NodeState =
  | 'idle' | 'bench' | 'queued' | 'running' | 'waiting' | 'done' | 'failed' | 'rejected' | 'planning' | 'ready' | 'pending';

interface StageNode {
  key: string;
  kind: 'supervisor' | 'agent' | 'answer';
  label: string;
  icon: string;
  x: number;
  y: number;
  /** where a newly selected agent flies in from (its place in the pool) */
  fx: number;
  fy: number;
  fly: boolean;
  /** on the bench (not in the pipeline): drawn small */
  small: boolean;
  state: NodeState;
  sub: string;
  drift: number;
}

interface StageEdge {
  key: string;
  d: string;
  state: 'idle' | 'flow' | 'done' | 'failed' | 'loop';
  /** the label's place (loop arcs) */
  lx?: number;
  ly?: number;
}

/** The plan that just failed, held on stage to show the rejection and the loop back to the supervisor. */
interface Loop {
  plan: Plan;
  status: Record<string, StepStatus>;
  failed: Set<string>;
  rejected: Set<string>;
}

const HEIGHT = 470;
const LOOP_MS = 2600;
const ANSWER_ICON = FLOW_ICONS.output;
const APPROVAL_ICON = FLOW_ICONS.review;
/** The supervisor's feedback lines (backend progress.py): "step s1 (rag) failed verification: ..." */
const FEEDBACK_RE = /^step (\S+) \(([^)]+)\) (failed verification|failed|rejected|revise)/;
/** A final text that says the supervisor gave up. */
const GAVE_UP_RE = /^(I could not|Stopped:|Plan is stuck)/;

const failing = (s: StepStatus | undefined) => s?.status === 'failed' || s?.status === 'rejected';

/** Stable 0..1 per name, so the scattered layout does not jump between renders. */
function hash(name: string): number {
  let h = 2166136261;
  for (const c of name) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return ((h >>> 0) % 1000) / 1000;
}

/**
 * The agent stage: every available agent floats around the supervisor. When a question comes in, the supervisor
 * plans, then catches the agents it chose: they fly into a pipeline in run order (parallel ones side by side),
 * the others step back to the bench. Data flows along the beams to the running agent, finished agents pop their
 * check, and the answer bursts at the end.
 *
 * When a step fails or the verifier rejects a result, the failed plan stays on stage for a moment: the failure
 * shakes red, the rejected agent is crossed out, and a red arc loops back to the supervisor, which replans. Then
 * the rejected agent goes to the bench (still marked rejected) and the new agents fly in.
 */
@Component({
  selector: 'alt-agent-stage',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './agent-stage.html',
  styleUrl: './agent-stage.css',
  host: { '[style.height.px]': 'height' },
})
export class AgentStage {
  readonly plan = input<Plan | null | undefined>(null);
  readonly status = input<Record<string, StepStatus>>({});
  readonly agents = input<string[]>([]);
  readonly phase = input<FlowPhase>('idle');
  readonly request = input<string>('');
  readonly final = input<string | null | undefined>(null);
  readonly replans = input(0);
  /** why earlier plans of this question failed (the supervisor's feedback) */
  readonly feedback = input<string[]>([]);
  /** step id -> "2.0 s" */
  readonly durations = input<Record<string, string>>({});
  readonly ask = output<void>();

  protected readonly height = HEIGHT;
  protected readonly loop = signal<Loop | null>(null);
  private readonly width = signal(960);
  /** Where each agent last stood outside the pipeline, so a newly selected one flies in from there. */
  private readonly lastSeen = new Map<string, { x: number; y: number }>();
  /** the latest view with a failed step, before the supervisor clears it to replan */
  private lastFailure: { plan: Plan; status: Record<string, StepStatus> } | null = null;
  private seenReplans = 0;
  private loopTimer: ReturnType<typeof setTimeout> | undefined;
  private readonly host = inject(ElementRef<HTMLElement>);

  /** Every agent: the cards' and the plan's (hitl approvals are drawn as their own steps). */
  private readonly pool = computed(() => {
    const names = new Set(this.agents());
    for (const s of this.plan()?.steps ?? []) if (s.agent !== 'hitl') names.add(s.agent);
    return [...names].sort();
  });

  /** Agents whose results this question rejected (they failed, or the verifier did not confirm them). */
  private readonly rejectedAgents = computed(() => {
    const out = new Set<string>();
    for (const line of this.feedback()) {
      const m = FEEDBACK_RE.exec(line);
      if (m && m[2] !== 'verifier' && m[2] !== 'hitl') out.add(m[2]);
    }
    return out;
  });

  /** Where each agent floats while it is not in the pipeline (an ellipse around the stage center). */
  private readonly homes = computed(() => {
    const names = this.pool();
    const w = this.width();
    const cx = w / 2;
    const cy = HEIGHT / 2 - 8;
    const rx = Math.min(w * 0.36, 400);
    const ry = HEIGHT * 0.33;
    const homes = new Map<string, { x: number; y: number }>();
    names.forEach((name, i) => {
      const angle = -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(1, names.length) + (hash(name) - 0.5) * 0.5;
      const r = 0.9 + hash(`${name}~`) * 0.18;
      homes.set(name, { x: cx + rx * r * Math.cos(angle), y: cy + ry * r * Math.sin(angle) });
    });
    return homes;
  });

  protected readonly layout = computed(() => {
    const loop = this.loop();
    const plan = loop?.plan ?? this.plan();
    const status = loop?.status ?? this.status();
    const phase = this.phase();
    const final = this.final();
    const gaveUp = !!final && GAVE_UP_RE.test(final);
    const w = this.width();
    const homes = this.homes();
    const midY = HEIGHT / 2 - 24;
    const nodes: StageNode[] = [];
    const edges: StageEdge[] = [];
    const planning = phase === 'running' && !plan;

    // ---- the supervisor: center while idle / planning, the start of the pipeline once there is a plan
    const sup = plan ? { x: Math.max(86, w * 0.08), y: midY } : { x: w / 2, y: HEIGHT / 2 - 8 };
    const supState: NodeState = loop || planning ? 'planning'
      : gaveUp || phase === 'error' ? 'failed' : phase === 'done' ? 'done'
      : phase === 'interrupted' ? 'waiting' : phase === 'running' ? 'running' : 'ready';
    const supSub = loop ? 'Replanning…' : planning ? 'Planning…' : gaveUp ? 'Gave up'
      : { failed: 'Failed', done: 'Done', waiting: 'Waiting for you', running: 'Orchestrating' }[supState as 'done'] ?? 'Ready';
    nodes.push({ key: 'supervisor', kind: 'supervisor', label: 'Supervisor', icon: FLOW_ICONS.supervisor,
      x: sup.x, y: sup.y, fx: sup.x, fy: sup.y, fly: false, small: false, state: supState,
      sub: this.replans() && !loop ? `${supSub} · replan ${this.replans()}` : supSub, drift: 0 });

    const inPlan = new Set((plan?.steps ?? []).map((s) => s.agent));
    // ---- agents not in the pipeline: floating around (no plan) or on the bench (with a plan)
    const bench = this.pool().filter((a) => !inPlan.has(a));
    const spacing = Math.min(150, (w - 120) / Math.max(1, bench.length));
    bench.forEach((name, i) => {
      const pos = plan ? { x: w / 2 + (i - (bench.length - 1) / 2) * spacing, y: HEIGHT - 52 } : homes.get(name)!;
      this.lastSeen.set(name, pos);
      const rejected = !!plan && this.rejectedAgents().has(name);
      nodes.push({ key: `pool:${name}`, kind: 'agent', label: name, icon: FLOW_ICONS[iconForAgent(name)],
        x: pos.x, y: pos.y, fx: pos.x, fy: pos.y, fly: false, small: !!plan,
        state: rejected ? 'rejected' : plan ? 'bench' : 'idle',
        sub: rejected ? 'Rejected' : plan ? 'Not needed' : planning ? 'Standing by' : 'Available', drift: hash(name) * 4 });
    });
    if (!plan) return { nodes, edges };

    // ---- the pipeline: one node per step, in waves (parallel steps stacked), then the answer
    const answer = { x: w - Math.max(86, w * 0.08), y: midY };
    const waves = planWaves(plan);
    const x0 = sup.x + Math.min(190, w * 0.17);
    const x1 = answer.x - Math.min(190, w * 0.17);
    const pos = new Map<string, { x: number; y: number }>();
    waves.forEach((wave, i) => {
      const x = waves.length === 1 ? (x0 + x1) / 2 : x0 + (i * (x1 - x0)) / (waves.length - 1);
      const gap = Math.min(116, (HEIGHT - 190) / Math.max(1, wave.length - 1));
      wave.forEach((step, j) => pos.set(step.id, { x, y: midY + (j - (wave.length - 1) / 2) * gap }));
    });
    const states = new Map<string, NodeState>();
    for (const step of plan.steps) {
      const p = pos.get(step.id) ?? { x: w / 2, y: midY };
      const from = this.lastSeen.get(step.agent) ?? homes.get(step.agent) ?? sup;
      const ui = status[step.id]?.status;
      let state: NodeState = ui === 'running' ? 'running' : ui === 'waiting_approval' ? 'waiting'
        : ui === 'done' ? 'done' : ui === 'failed' || ui === 'rejected' ? 'failed' : 'queued';
      let sub = { running: 'Running…', waiting: 'Needs approval', failed: ui === 'rejected' ? 'Rejected' : 'Failed',
        queued: ui === 'skipped' ? 'Skipped' : 'Queued',
        done: this.durations()[step.id] ? `Done · ${this.durations()[step.id]}` : 'Done' }[state as 'running'];
      if (loop?.rejected.has(step.id)) {
        state = 'rejected';
        sub = 'Rejected by the verifier';
      } else if (loop?.failed.has(step.id) && step.agent === 'verifier') {
        sub = 'Not verified';
      }
      states.set(step.id, state);
      const hitl = step.kind === 'hitl';
      nodes.push({ key: `${step.id}:${step.agent}`, kind: 'agent', label: hitl ? 'Approval' : step.agent,
        icon: hitl ? APPROVAL_ICON : FLOW_ICONS[iconForAgent(step.agent)], x: p.x, y: p.y, fx: from.x, fy: from.y,
        fly: true, small: false, state, sub: `${step.id} · ${sub}`, drift: 0 });
    }
    nodes.push({ key: 'answer', kind: 'answer', label: 'Answer', icon: ANSWER_ICON, x: answer.x, y: answer.y,
      fx: answer.x, fy: answer.y, fly: false, small: false,
      state: loop ? 'pending' : gaveUp || phase === 'error' ? 'failed' : final ? 'done' : 'pending',
      sub: loop ? 'Waiting' : gaveUp ? 'Could not answer' : final ? 'Answer ready' : 'Waiting', drift: 0 });

    // ---- beams: supervisor -> first steps, dependencies, last steps -> answer
    const ids = new Set(plan.steps.map((s) => s.id));
    const used = new Set<string>();
    const beam = (from: string, a: { x: number; y: number }, to: string, b: { x: number; y: number }, srcDone: boolean,
                  target: NodeState) => {
      const xa = a.x + 31;
      const xb = b.x - 33;
      const dx = Math.max(36, (xb - xa) / 2);
      const state: StageEdge['state'] = !srcDone ? 'idle' : target === 'failed' || target === 'rejected' ? 'failed'
        : target === 'done' ? 'done' : target === 'running' || target === 'waiting' || target === 'pending' ? 'flow' : 'idle';
      edges.push({ key: `${from}->${to}`, d: `M ${xa} ${a.y} C ${xa + dx} ${a.y}, ${xb - dx} ${b.y}, ${xb} ${b.y}`, state });
    };
    for (const step of plan.steps) {
      const deps = [...step.depends_on, ...step.after].filter((d) => ids.has(d));
      deps.forEach((d) => used.add(d));
      const target = states.get(step.id)!;
      if (!deps.length) beam('supervisor', sup, step.id, pos.get(step.id)!, supState !== 'planning' || !!loop, target);
      const doneish = (d: string) => states.get(d) === 'done' || states.get(d) === 'rejected';
      for (const d of deps) beam(d, pos.get(d)!, step.id, pos.get(step.id)!, doneish(d), target);
    }
    for (const step of plan.steps.filter((s) => !used.has(s.id))) {
      const endState: NodeState = loop ? 'queued' : gaveUp ? 'failed' : final ? 'done' : 'pending';
      beam(step.id, pos.get(step.id)!, 'answer', answer, states.get(step.id) === 'done', endState);
    }

    // ---- the loop back: from each failure, a red arc over the pipeline to the supervisor
    for (const id of loop?.failed ?? []) {
      const p = pos.get(id);
      if (!p) continue;
      const top = Math.min(p.y, sup.y) - 190;
      edges.push({ key: `loop:${id}`, state: 'loop', lx: (p.x + sup.x) / 2, ly: Math.max(18, top + 36),
        d: `M ${p.x} ${p.y - 34} C ${p.x} ${top}, ${sup.x} ${top}, ${sup.x} ${sup.y - 42}` });
    }
    return { nodes, edges };
  });

  constructor() {
    effect(() => {
      const plan = this.plan();
      const status = this.status();
      const replans = this.replans();
      untracked(() => this.watch(plan, status, replans));
    });
    const resize = new ResizeObserver(([entry]) => this.width.set(Math.max(560, Math.round(entry.contentRect.width))));
    afterNextRender(() => resize.observe(this.host.nativeElement));
    inject(DestroyRef).onDestroy(() => {
      resize.disconnect();
      clearTimeout(this.loopTimer);
    });
  }

  /** Remember the latest failure; when the supervisor replans (replans goes up), hold it on stage for a moment. */
  private watch(plan: Plan | null | undefined, status: Record<string, StepStatus>, replans: number): void {
    if (replans < this.seenReplans) {  // a new question
      this.seenReplans = replans;
      this.lastFailure = null;
      clearTimeout(this.loopTimer);
      this.loop.set(null);
    }
    if (plan && Object.values(status).some(failing)) this.lastFailure = { plan, status };
    if (replans <= this.seenReplans) return;
    this.seenReplans = replans;
    const failure = this.lastFailure;
    this.lastFailure = null;
    if (!failure) return;  // replanned for another reason (e.g. an invalid plan): nothing to show
    const failed = new Set(Object.keys(failure.status).filter((id) => failing(failure.status[id])));
    const rejected = new Set<string>();
    for (const step of failure.plan.steps) {
      if (failed.has(step.id) && step.agent === 'verifier') step.depends_on.forEach((d) => rejected.add(d));
    }
    this.loop.set({ plan: failure.plan, status: failure.status, failed, rejected });
    clearTimeout(this.loopTimer);
    this.loopTimer = setTimeout(() => this.loop.set(null), LOOP_MS);
  }
}
