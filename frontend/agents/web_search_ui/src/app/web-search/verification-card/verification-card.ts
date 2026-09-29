import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';

import { formatSeconds } from '../format';
import { Handoff, RunDetails } from '../web-search.models';

type Outcome = 'passed' | 'failed' | 'sent' | 'unreachable' | 'not-sent' | 'skipped';

interface Target {
  key: string;
  outcome: Outcome;
  label: string;
  route: string;
  summary: string;
  issues: string[];
  warnings: string[];
  reasons: { verified: boolean; reason: string }[];
}

/** The verifier's verdict fields, from the handoff (copied by the backend) or its raw response. */
function judgements(h: Handoff): { verified: boolean; reason: string }[] {
  const raw = (h.response as { judgements?: Record<string, { verified?: boolean; reason?: string }> } | undefined)
    ?.judgements;
  return raw ? Object.values(raw).map((j) => ({ verified: j.verified !== false, reason: j.reason ?? '' })) : [];
}

function toTarget(key: string, h: Handoff): Target {
  const route = h.path && h.host ? `${h.path} @ ${h.host}` : key;
  const outcome: Outcome =
    h.status === 'failed' ? 'unreachable'
    : h.status === 'not_configured' ? 'skipped'
    : h.passed === true ? 'passed'
    : h.passed === false ? 'failed'
    : 'sent';
  const label = {
    passed: 'Verification passed',
    failed: 'Verification failed',
    sent: 'Delivered',
    unreachable: 'Not reachable',
    'not-sent': 'Not sent',
    skipped: 'Not configured',
  }[outcome];
  return {
    key,
    outcome,
    label,
    route,
    summary: h.status === 'failed' ? (h.error ?? '') : (h.summary ?? ''),
    issues: h.issues ?? [],
    warnings: h.warnings ?? [],
    reasons: judgements(h),
  };
}

/**
 * What the output agents answered for one run: one row per route the output was POSTed to (a verifier's verdict is
 * shown as passed / failed), with the time the "Send output" step took (all routes are called in parallel).
 */
@Component({
  selector: 'alt-ws-verification-card',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './verification-card.html',
  styleUrl: './verification-card.css',
})
export class VerificationCard {
  readonly result = input.required<RunDetails>();
  readonly retrying = input(false);
  readonly retry = output<string>();

  private readonly step = computed(() => this.result().steps.find((s) => s.id === 'verify'));

  protected readonly seconds = computed(() => formatSeconds(this.step()?.duration_s));

  protected readonly targets = computed<Target[]>(() => {
    const r = this.result();
    const all = r.handoffs ?? (r.verification ? { verifier: r.verification } : {});
    const targets = Object.entries(all).map(([key, h]) => toTarget(key, h));
    const step = this.step();
    if (!targets.length && step && (step.status === 'failed' || step.status === 'skipped')) {
      // Nothing was sent: no route found on the network, or WEB_SEARCH_VERIFIER_PATH is empty.
      targets.push({
        key: 'verify',
        outcome: step.status === 'failed' ? 'not-sent' : 'skipped',
        label: step.status === 'failed' ? 'Not sent' : 'Not configured',
        route: 'Output agents',
        summary: step.detail,
        issues: [],
        warnings: [],
        reasons: [],
      });
    }
    return targets;
  });

  /** Card border / header colour: failed wins, then warnings, then passed. */
  protected readonly overall = computed<'ok' | 'bad' | 'warn' | 'neutral'>(() => {
    const outcomes = this.targets().map((t) => t.outcome);
    if (outcomes.some((o) => o === 'failed')) return 'bad';
    if (outcomes.some((o) => o === 'unreachable' || o === 'not-sent')) return 'warn';
    if (outcomes.some((o) => o === 'passed')) return 'ok';
    return 'neutral';
  });

  protected readonly canRetry = computed(() => this.targets().some((t) => t.outcome !== 'skipped'));
}
