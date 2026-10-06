/**
 * TypeScript mirror of backend/shared/agentkit/src/agentkit/contracts.py
 * and the orchestrator state (backend/superviser_agent/.../state.py).
 */

export type StepKind = 'agent' | 'hitl';

export interface Step {
  id: string;
  agent: string;
  kind: StepKind;
  objective: string;
  params: Record<string, unknown>;
  depends_on: string[];
  after: string[];
  added_by: 'supervisor' | 'policy';
  /** What a good result of this step looks like (written by the supervisor's LLM). */
  expected_output?: string;
}

export interface Plan {
  plan_id: string;
  version: number;
  goal: string;
  reasoning: string;
  /** What "done" means; the supervisor reviews the results against it. */
  success_criteria?: string[];
  steps: Step[];
}

export type StepUiStatus = 'queued' | 'running' | 'waiting_approval' | 'done' | 'failed' | 'rejected' | 'skipped';

export interface StepStatus {
  status: StepUiStatus;
  agent: string;
  updated_at: string;
  remote_thread?: string | null;
  detail?: string | null;
}

/** Agent-specific output. Every agent returns at least `status` and `summary`. */
export interface AgentOutput {
  status?: string;
  summary?: string;
  [key: string]: unknown;
}

export interface AgentResult {
  step_id: string;
  agent: string;
  status: 'ok' | 'failed' | 'rejected' | 'revise' | 'pending';
  output: AgentOutput;
  error?: string | null;
}

export interface ChatMessage {
  type: 'human' | 'ai' | string;
  content: string;
  id?: string;
}

export interface OrchestratorValues {
  request?: string;
  messages?: ChatMessage[];
  plan?: Plan | null;
  results?: Record<string, AgentResult>;
  step_status?: Record<string, StepStatus>;
  feedback?: string[];
  replans?: number;
  /** Why the supervisor was called again: 'failed' (a step failed / a verifier rejected data) | 'complete'. */
  review_reason?: string | null;
  final?: string | null;
}

export type ApprovalMode = 'none' | 'internal' | 'gate';

export interface AgentCard {
  name: string;
  version: string;
  description: string;
  when_to_use: string;
  when_not_to_use: string;
  examples: string[];
  approval_mode: ApprovalMode;
  /** source | transform | final_answer | verifier | action: how the supervisor uses the agent. */
  role?: 'source' | 'transform' | 'final_answer' | 'verifier' | 'action' | null;
  /** Sends or changes something outside the platform. */
  side_effects?: boolean;
  params_schema: { properties?: Record<string, { description?: string; type?: string }> } & Record<string, unknown>;
  output_schema: Record<string, unknown>;
  owner: string;
}

/* ---- admin view of every agent (GET /platform/admin/agents) ---- */

/** up | down (found, card failed) | not_found (no machine on the network) | paused | in_process | disabled (not a node) */
export type AgentAdminStatus = 'up' | 'down' | 'not_found' | 'paused' | 'in_process' | 'disabled';

export interface AgentAdmin {
  name: string;
  /** A node of the supervisor graph (enabled in config/agents.*.yaml). */
  node: boolean;
  port: number | null;
  graph_id: string | null;
  /** AGENT_<NAME>_URL: a fixed machine instead of the network search. */
  pinned_url: string | null;
  status: AgentAdminStatus;
  reachable: boolean;
  paused: boolean;
  /** The machine it was found on, e.g. http://192.168.1.34:8000. */
  url: string | null;
  latency_ms: number | null;
  /** Unix seconds of the last check. */
  checked_at: number | null;
  error: string | null;
  /** The card the supervisor plans with (its own, with the customised planning text over it). */
  card: AgentCard | null;
  /** Planning text customised in the admin console (saved on the supervisor's machine). */
  overrides: Partial<PlanningText>;
  /** The agent's own planning text (what a reset goes back to); null until its card was fetched once. */
  planning_defaults: PlanningText | null;
}

/** The fields of a card the supervisor reads when it chooses agents (customisable per agent). */
export interface PlanningText {
  description: string;
  when_to_use: string;
  when_not_to_use: string;
  examples: string[];
}

export interface PlatformAdmin {
  /** llm_model: SUPERVISOR_LLM_MODEL (null: the supervisor cannot plan). */
  supervisor: { port: number; graph_id: string; llm_model?: string | null };
  transport: string;
  subnet: string | null;
  agents: AgentAdmin[];
}

export type AgentAdminAction = 'recheck' | 'pause' | 'resume';

/** The supervisor's safety rules (config/policies.yaml; an admin can change them at runtime). */
export interface PlatformPolicies {
  max_steps: number;
  max_replans: number;
  max_clarifications: number;
  /** How often the supervisor's LLM may fix a plan that cannot run. */
  max_plan_repairs?: number;
  verify_before_approval: boolean;
  /** Not used since the platform checks the final answer (kept so older saved policies still load). */
  verify_before_synthesis?: boolean;
  verify_final: boolean;
  allowed_email_domains: string[];
}

/** One admin action (GET /platform/admin/audit), newest first. */
export interface AuditEntry {
  at: string;
  action: string;
  target: string;
  detail: string;
  by: string;
}

/* ---- interrupts raised by the orchestrator (what the human must answer) ---- */

export interface ClarificationInterrupt {
  kind: 'clarification';
  question: string;
}

/** An agent (e.g. communication) paused at its own interrupt(); `request` is the agent's payload. */
export interface AgentApprovalInterrupt {
  kind: 'agent_approval';
  step_id: string;
  agent: string;
  objective: string;
  request: Record<string, unknown>;
}

/** Plan-level hitl_gate step. */
export interface GateApprovalInterrupt {
  kind: 'approval';
  step_id: string;
  objective: string;
  context: Record<string, unknown>;
}

export type InterruptPayload = ClarificationInterrupt | AgentApprovalInterrupt | GateApprovalInterrupt;

/** Plan step the interrupt belongs to (none for clarifications). */
export function interruptStepId(payload: InterruptPayload | null | undefined): string | null {
  return payload && payload.kind !== 'clarification' ? payload.step_id : null;
}

/** Custom stream events emitted by nodes (agentkit/events.py). */
export interface RunEvent {
  type: string;
  at?: string;
  [key: string]: unknown;
}

export type ThreadStatus = 'idle' | 'busy' | 'interrupted' | 'error';

export interface ThreadSummary {
  threadId: string;
  status: ThreadStatus;
  createdAt: string;
  updatedAt: string;
  values: OrchestratorValues;
  interrupt: InterruptPayload | null;
}
