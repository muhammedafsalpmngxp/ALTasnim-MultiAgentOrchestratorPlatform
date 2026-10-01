import { RunEvent } from './models';

const LABELS: Record<string, (e: RunEvent) => string> = {
  supervisor_decision: (e) => `Supervisor decided: ${e['action']}. ${e['reasoning'] ?? ''}`,
  plan: () => 'Plan created and checked by policy',
  step_started: (e) => `${e['step_id']} · ${e['agent']} started`,
  step_finished: (e) => `${e['step_id']} · ${e['agent']} finished (${e['status']})`,
  step_waiting_approval: (e) => `${e['step_id']} · ${e['agent']} is waiting for approval`,
  progress: (e) => `${e['agent']}: ${e['message']}`,
  final: () => 'Answer ready',
};

/** One live event of a run in words, e.g. "s1 · rag started". */
export function describeEvent(e: RunEvent): string {
  return (LABELS[e.type] ?? (() => e.type))(e);
}
