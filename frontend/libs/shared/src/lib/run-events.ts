import { RunEvent } from './models';

const LABELS: Record<string, (e: RunEvent) => string> = {
  supervisor_thinking: (e) => (e['mode'] === 'review' ? 'Supervisor is reviewing the results…' : 'Supervisor is planning…'),
  supervisor_decision: (e) =>
    `Supervisor ${e['mode'] === 'review' ? 'reviewed' : 'decided'}: ${e['action']}. ` +
    `${e['understanding'] ? `${e['understanding']} — ` : ''}${e['reasoning'] ?? ''}`,
  plan: (e) => `Plan v${(e['plan'] as { version?: number } | undefined)?.version ?? 1} ready to run`,
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
