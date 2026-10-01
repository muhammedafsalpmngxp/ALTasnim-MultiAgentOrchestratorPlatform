import { AgentAdminStatus } from '@altasnim/shared';

/** One micro-frontend from the shell's federation manifest, and whether its dev server answers. */
export interface Ui {
  name: string;
  url: string;
  port: string;
  up: boolean | null;
}

/** One check of an agent by the supervisor: when (unix seconds), its card latency, whether it answered. */
export interface Sample {
  at: number;
  ms: number | null;
  up: boolean;
}

export const STATUS: Record<AgentAdminStatus, { label: string; tone: string }> = {
  up: { label: 'Up', tone: 'ok' },
  in_process: { label: 'In-process', tone: 'ok' },
  paused: { label: 'Paused', tone: 'warn' },
  down: { label: 'Down', tone: 'danger' },
  not_found: { label: 'Not found', tone: 'danger' },
  disabled: { label: 'Not a node', tone: 'muted' },
};

export const isUp = (status: AgentAdminStatus) => status === 'up' || status === 'in_process';

export function portOf(url: string): string {
  try {
    return new URL(url).port || '80';
  } catch {
    return '?';
  }
}

/** A dev server answers (no-cors: any reply counts, only a network error means down). */
export function answers(url: string): Promise<boolean> {
  return fetch(url, { mode: 'no-cors', cache: 'no-store' }).then(
    () => true,
    () => false,
  );
}

/** milliseconds ago -> "just now", "12 s ago", "3 min ago", "2 h ago" */
export function agoMs(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 3) return 'just now';
  if (s < 90) return `${s} s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}

export function duration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  return s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

/** Per-viewer UI preferences (storage may be blocked: then nothing is remembered). */
export function remembered(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function remember(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // not remembered
  }
}
