/**
 * TypeScript mirror of backend/shared/agentkit/src/agentkit/contracts.py
 * and the orchestrator state (backend/orchestrator-agent/.../state.py).
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
}

export interface Plan {
  plan_id: string;
  version: number;
  goal: string;
  reasoning: string;
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
  params_schema: { properties?: Record<string, { description?: string; type?: string }> } & Record<string, unknown>;
  output_schema: Record<string, unknown>;
  owner: string;
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
