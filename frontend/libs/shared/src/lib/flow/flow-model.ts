/**
 * Turns the supervisor's plan into a visual flow:
 *
 *   Input → Routing (supervisor) → Chaining / Parallelization / Reflection → Human-in-the-loop → Action → Output
 *
 * Nothing here is hard-coded per agent: stages are derived from the plan (waves from depends_on/after)
 * and from the agent cards (approval_mode). A new agent shows up automatically.
 */
import { AgentCard, Plan, Step, StepStatus, StepUiStatus } from '../models';
import { FlowIcon, iconForAgent } from './flow-icons';

export type FlowPhase = 'idle' | 'running' | 'interrupted' | 'done' | 'error';
export type NodeState = 'idle' | 'queued' | 'running' | 'waiting' | 'done' | 'failed' | 'rejected';
export type NodeKind = 'input' | 'supervisor' | 'agent' | 'review' | 'stop' | 'output';

export interface FlowNode {
  id: string;
  kind: NodeKind;
  label: string;
  sub: string;
  icon: FlowIcon;
  state: NodeState;
  policy?: boolean; // inserted by plan_guard policy, not by the supervisor
  badge?: string;
}

export interface FlowColumn {
  key: string;
  stage: string;
  nodes: FlowNode[];
}

export interface FlowEdge {
  from: string;
  to: string;
  label?: string;
  tone?: 'ok' | 'danger';
  active: boolean;
  dashed?: boolean;
}

export interface FlowGraph {
  columns: FlowColumn[];
  edges: FlowEdge[];
}

export interface FlowArgs {
  plan?: Plan | null;
  status?: Record<string, StepStatus>;
  waitingStepId?: string | null;
  cards?: Record<string, AgentCard>;
  request?: string;
  phase: FlowPhase;
  final?: string | null;
  replans?: number;
}

/** Group steps into waves: a step runs after everything in depends_on + after. Same wave = parallel. */
export function planWaves(plan: Plan): Step[][] {
  const byId = new Map(plan.steps.map((s) => [s.id, s]));
  const level = new Map<string, number>();
  const visit = (step: Step, seen: Set<string>): number => {
    if (level.has(step.id)) return level.get(step.id)!;
    if (seen.has(step.id)) return 0; // cycle guard (the backend rejects cycles anyway)
    seen.add(step.id);
    const deps = [...step.depends_on, ...step.after].map((id) => byId.get(id)).filter((s): s is Step => !!s);
    const value = deps.length ? 1 + Math.max(...deps.map((d) => visit(d, seen))) : 0;
    level.set(step.id, value);
    return value;
  };
  plan.steps.forEach((s) => visit(s, new Set()));
  const waves: Step[][] = [];
  for (const step of plan.steps) (waves[level.get(step.id)!] ??= []).push(step);
  return waves.filter(Boolean);
}

const UI_TO_NODE: Record<StepUiStatus, NodeState> = {
  queued: 'queued',
  running: 'running',
  waiting_approval: 'waiting',
  done: 'done',
  failed: 'failed',
  rejected: 'rejected',
  skipped: 'idle',
};

const truncate = (text: string, n: number) => (text.length > n ? text.slice(0, n - 1) + '…' : text);

function outputState(a: FlowArgs): NodeState {
  if (a.phase === 'error') return 'failed';
  if (a.phase !== 'done' || !a.final) return a.request ? 'queued' : 'idle';
  if (a.final.startsWith('Stopped')) return 'rejected';
  if (a.final.startsWith('I could not')) return 'failed';
  return 'done';
}

export function buildFlow(a: FlowArgs): FlowGraph {
  const cards = a.cards ?? {};
  const columns: FlowColumn[] = [];
  const edges: FlowEdge[] = [];
  const state = new Map<string, NodeState>();
  const add = (column: FlowColumn) => {
    column.nodes.forEach((n) => state.set(n.id, n.state));
    columns.push(column);
  };
  const edge = (from: string, to: string, extra: Partial<FlowEdge> = {}) =>
    edges.push({ from, to, active: state.get(from) === 'done', ...extra });

  // 1. Input
  add({
    key: 'input',
    stage: 'Input',
    nodes: [{
      id: 'input', kind: 'input', label: 'User request', icon: 'input',
      sub: a.request ? truncate(a.request, 70) : 'Waiting for a request',
      state: a.request ? 'done' : 'idle',
    }],
  });

  // 2. Routing: the supervisor decides the flow
  const planning = !a.plan && a.phase === 'running';
  const answeredDirectly = !a.plan && a.phase === 'done' && !!a.request;
  add({
    key: 'routing',
    stage: 'Routing',
    nodes: [{
      id: 'supervisor', kind: 'supervisor', label: 'Supervisor', icon: 'supervisor',
      sub: a.plan ? `Planned ${a.plan.steps.length} steps · v${a.plan.version}` : planning ? 'Planning the flow…' : 'Decides which agents run',
      state: a.plan || answeredDirectly ? 'done' : planning ? 'running' : a.phase === 'error' ? 'failed' : 'idle',
      badge: a.replans ? `↻ replanned ×${a.replans}` : undefined,
    }],
  });
  edge('input', 'supervisor');

  const output: FlowNode = {
    id: 'output', kind: 'output', label: 'Answer', icon: 'output',
    sub: a.final ? truncate(a.final.split('\n')[0], 60) : 'Final response',
    state: outputState(a),
  };

  // ---- no plan yet: show the capability map (every available agent)
  if (!a.plan) {
    const agents = Object.values(cards);
    add({
      key: 'agents',
      stage: 'Agents',
      nodes: agents.length
        ? agents.map((c) => ({
            id: `agent:${c.name}`, kind: 'agent' as const, label: c.name, icon: iconForAgent(c.name),
            sub: truncate(c.description, 60), state: 'idle' as const,
          }))
        : [{ id: 'agent:none', kind: 'agent', label: 'No agents online', icon: 'agent', sub: 'Start the agent deployments', state: 'idle' }],
    });
    add({
      key: 'hitl',
      stage: 'Human-in-the-loop',
      nodes: [{ id: 'review', kind: 'review', label: 'Review', icon: 'review', sub: 'When an agent needs approval', state: 'idle' }],
    });
    add({ key: 'output', stage: 'Output', nodes: [output] });
    for (const c of agents) {
      edge('supervisor', `agent:${c.name}`, { dashed: true, active: false });
      edge(`agent:${c.name}`, 'review', { dashed: true, active: false });
    }
    edge('review', 'output', { dashed: true, active: false });
    if (answeredDirectly) edge('supervisor', 'output', { label: 'answered', active: true });
    return { columns, edges };
  }

  // ---- plan: one column per wave (+ review column before steps that need a human)
  const plan = a.plan;
  const status = a.status ?? {};
  const needsReview = (s: Step) => s.kind === 'agent' && cards[s.agent]?.approval_mode === 'internal';
  const referenced = new Set(plan.steps.flatMap((s) => [...s.depends_on, ...s.after]));

  planWaves(plan).forEach((wave) => {
    const reviewed = wave.filter(needsReview);

    if (reviewed.length) {
      add({
        key: `hitl-${wave[0].id}`,
        stage: 'Human-in-the-loop',
        nodes: reviewed.map((s) => {
          const st = status[s.id]?.status;
          const nodeState: NodeState =
            a.waitingStepId === s.id ? 'waiting' : st === 'done' ? 'done' : st === 'rejected' ? 'rejected' : 'queued';
          return {
            id: `review:${s.id}`, kind: 'review' as const, label: 'Review', icon: 'review' as const,
            sub: a.waitingStepId === s.id ? 'Waiting for your approval' : `Approve: ${truncate(s.objective, 48)}`,
            state: nodeState,
          };
        }),
      });
    }

    const stage = wave.every((s) => s.agent === 'verifier')
      ? 'Reflection'
      : wave.every((s) => s.kind === 'hitl')
        ? 'Human-in-the-loop'
        : reviewed.length
          ? 'Action'
          : wave.length > 1
            ? 'Parallelization'
            : 'Chaining';

    const nodes: FlowNode[] = [];
    for (const s of wave) {
      const st = status[s.id]?.status;
      let nodeState: NodeState = st ? UI_TO_NODE[st] : 'queued';
      if (a.waitingStepId === s.id) nodeState = needsReview(s) ? 'queued' : 'waiting';
      if (needsReview(s) && st === 'rejected') nodeState = 'idle';
      nodes.push({
        id: s.id,
        kind: s.kind === 'hitl' ? 'review' : 'agent',
        label: s.kind === 'hitl' ? 'Review' : s.agent,
        icon: s.kind === 'hitl' ? 'review' : iconForAgent(s.agent),
        sub: truncate(s.objective, 56),
        state: nodeState,
        policy: s.added_by === 'policy',
      });
      if (needsReview(s)) {
        nodes.push({
          id: `stop:${s.id}`, kind: 'stop', label: 'Stopped', icon: 'stop',
          sub: 'Rejected by approver', state: st === 'rejected' ? 'rejected' : 'idle',
        });
      }
    }
    add({ key: `wave-${wave[0].id}`, stage, nodes });
  });

  add({ key: 'output', stage: 'Output', nodes: [output] });

  // edges: supervisor → first steps, dependency → step (via review when needed), leaves → output
  for (const s of plan.steps) {
    // When policy inserted steps before this one (verifier / approval), draw only that chain:
    // the data dependencies already flow into those policy steps, so direct lines would just add clutter.
    const preds = [...new Set(s.after.length ? s.after : s.depends_on)];
    const target = needsReview(s) ? `review:${s.id}` : s.id;
    if (!preds.length) edge('supervisor', target);
    for (const p of preds) edge(p, target);
    if (needsReview(s)) {
      const review = state.get(`review:${s.id}`);
      edge(`review:${s.id}`, s.id, { label: 'Approved', tone: 'ok', active: review === 'done' });
      edge(`review:${s.id}`, `stop:${s.id}`, {
        label: 'Rejected', tone: 'danger', active: review === 'rejected', dashed: review !== 'rejected',
      });
    }
    if (!referenced.has(s.id)) edge(s.id, 'output');
  }
  return { columns, edges };
}
