/** Shape of one entry of the verifier's GET /verify/calls (backend/verifier_agent/.../calls.py). */

/** One part of the user's question, and whether the answer responds to it. */
export interface Part {
  part: string;
  kind?: 'fact' | 'action';
  answered: boolean;
}

export interface VerifyResult {
  status: 'ok' | 'failed' | string;
  passed: boolean;
  summary: string;
  issues: string[];
  warnings: string[];
  missing?: string[];
  rejected_steps?: string[];
  fix?: 'none' | 'rewrite_answer';
  parts?: Part[];
  checked?: { answer_step?: string | null; model?: string | null };
}

export interface VerifyCall {
  id: string;
  received_at: string;
  task_id: string | null;
  question: string;
  answer_step: string | null;
  answer: string;
  result?: VerifyResult;
  error?: string;
  duration_ms?: number | null;
}

export type Verdict = 'passed' | 'failed' | 'error' | 'running';

export function verdictOf(call: VerifyCall): Verdict {
  if (call.error) return 'error';
  if (!call.result) return 'running';
  return call.result.passed ? 'passed' : 'failed';
}

/** What the supervisor is told to do after a failed check. */
export const FIX_LABEL: Record<string, string> = {
  rewrite_answer: 'Write the answer again so it matches the question',
  none: 'No step blamed (the check could not run)',
};

/** "just now", "42s ago", "5m ago", "3h ago", or a date. */
export function timeAgo(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 5) return 'just now';
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}
