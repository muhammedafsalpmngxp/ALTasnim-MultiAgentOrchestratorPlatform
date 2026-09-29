/** Shape of one entry of the verifier's GET /verify/calls (backend/verifier-agent/.../api.py). */
export interface VerifyResult {
  status: 'ok' | 'failed' | string;
  passed: boolean;
  issues: string[];
  warnings: string[];
  summary: string;
}

export interface VerifyTask {
  task_id?: string;
  objective?: string;
  params?: Record<string, unknown>;
  inputs?: Record<string, unknown>;
}

export interface VerifyCall {
  id: string;
  received_at: string;
  client: string;
  question: string;
  task: VerifyTask;
  payload: Record<string, unknown>;
  result?: VerifyResult;
  error?: string;
  duration_ms?: number;
}

export type Verdict = 'passed' | 'failed' | 'error' | 'running';

export function verdictOf(call: VerifyCall): Verdict {
  if (call.error) return 'error';
  if (!call.result) return 'running';
  return call.result.passed ? 'passed' : 'failed';
}

/** One web result inside a step output (web-search agent's `findings`). */
export interface Finding {
  rank: number;
  title: string;
  url: string;
  domain: string;
  content: string;
}

/** One earlier step the verifier checked (an entry of task.inputs). */
export interface CheckedStep {
  id: string;
  status: string | null;
  summary: string;
  findings: Finding[];
  sources: string[];
  checks: Check[];
  raw: unknown;
}

export interface Check {
  label: string;
  passed: boolean;
  detail?: string;
}

/**
 * The verifier's rules (nodes/checks.py), each marked failed when the server reported the matching issue.
 * The server's `issues` stay the source of truth; this only groups them per step.
 */
const RULES: { label: string; issue: string }[] = [
  { label: 'Output is an object', issue: 'output is not an object' },
  { label: 'Step reported ok', issue: 'step reported status' },
  { label: 'Has summary', issue: 'missing summary' },
  { label: 'Has findings', issue: 'no findings' },
  { label: 'Source URLs valid', issue: 'invalid source URLs' },
];

export function checkedSteps(call: VerifyCall): CheckedStep[] {
  const issues = call.result?.issues ?? [];
  return Object.entries(call.task?.inputs ?? {}).map(([id, out]) => {
    const o = (typeof out === 'object' && out !== null ? out : {}) as Record<string, unknown>;
    const checks = RULES.map((rule) => {
      const hit = issues.find((i) => i.startsWith(`${id}: ${rule.issue}`));
      return { label: rule.label, passed: !hit, detail: hit?.slice(id.length + 2) };
    });
    return {
      id,
      status: typeof o['status'] === 'string' ? (o['status'] as string) : null,
      summary: String(o['summary'] ?? ''),
      findings: toFindings(o['findings']),
      sources: Array.isArray(o['sources']) ? o['sources'].map(String) : [],
      checks,
      raw: out,
    };
  });
}

function toFindings(value: unknown): Finding[] {
  if (!Array.isArray(value)) return [];
  return value.map((f, i) => {
    const o = (typeof f === 'object' && f !== null ? f : { content: String(f) }) as Record<string, unknown>;
    const url = String(o['url'] ?? '');
    return {
      rank: Number(o['rank'] ?? i + 1),
      title: String(o['title'] ?? ''),
      url,
      domain: domainOf(url),
      content: String(o['content'] ?? o['snippet'] ?? ''),
    };
  });
}

export function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

/** "just now", "42s ago", "5m ago", "3h ago", or a date. */
export function timeAgo(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 5) return 'just now';
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}
