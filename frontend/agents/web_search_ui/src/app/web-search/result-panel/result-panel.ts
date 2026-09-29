import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';

import { EvidenceCard } from '../evidence-card/evidence-card';
import { formatDate, formatSeconds } from '../format';
import { PipelineFlow } from '../pipeline-flow/pipeline-flow';
import { Handoff, RunDetails } from '../web-search.models';

/**
 * Display-only view of one run's full details (the console on the agent page): the question, all ranked
 * evidence (the top 3 are what the verifier gets), sources, flow. The platform's step list shows the step result instead (widget/).
 */
@Component({
  selector: 'alt-ws-result-panel',
  imports: [EvidenceCard, PipelineFlow],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './result-panel.html',
  styleUrl: './result-panel.css',
})
export class ResultPanel {
  readonly result = input.required<RunDetails>();
  /** Show the processing flow (collapsed). Off when the parent already draws it live. */
  readonly showFlow = input(true);
  /** A "Retry" is running (disables the button). */
  readonly retrying = input(false);
  /** "Retry" clicked (trace id): the parent sends another request to the output agents. */
  readonly retry = output<string>();

  /** One chip per target the output was sent to (older runs: only `verification`). */
  protected readonly handoffs = computed<(Handoff & { name: string })[]>(() => {
    const r = this.result();
    const all = r.handoffs ?? (r.verification ? { verifier: r.verification } : {});
    return Object.entries(all).map(([key, h]) => ({
      ...h,
      name: h.path && h.host ? `${h.path.replace(/^\//, '')} @ ${h.host}` : key,
    }));
  });

  protected readonly formatDate = formatDate;
  protected readonly formatSeconds = formatSeconds;
}
