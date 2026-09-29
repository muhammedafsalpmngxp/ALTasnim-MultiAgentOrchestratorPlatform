import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription } from 'rxjs';

import { PipelineFlow } from '../pipeline-flow/pipeline-flow';
import { ResultPanel } from '../result-panel/result-panel';
import { WebSearchApi } from '../web-search-api';
import {
  Freshness,
  PipelineStep,
  SearchStreamEvent,
  StepId,
  WEB_SEARCH_RESULT_EVENT,
  RunDetails,
} from '../web-search.models';

const CLOCK_TICK_MS = 100;

/**
 * The agent team's test console: runs this agent once through its own /custom/search/stream route and draws the
 * processing flow live. Read-only on public data; plans with other agents always go through the orchestrator.
 */
@Component({
  selector: 'alt-ws-search-console',
  imports: [PipelineFlow, ResultPanel],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './search-console.html',
  styleUrl: './search-console.css',
})
export class SearchConsole {
  private readonly api = inject(WebSearchApi);
  private readonly destroyRef = inject(DestroyRef);

  readonly searched = output<RunDetails>();

  protected readonly queryText = signal('');
  protected readonly response = signal<RunDetails | null>(null);
  protected readonly steps = signal<PipelineStep[]>([]);
  protected readonly selectedTopK = signal(5);
  protected readonly freshness = signal<Freshness | ''>('');
  protected readonly loading = signal(false);
  protected readonly retrying = signal(false);
  protected readonly error = signal<string | null>(null);

  // Live clock for the running step / total while a search is in flight.
  private readonly now = signal(Date.now());
  private searchStartedAt = 0;
  private readonly stepStartedAt = new Map<StepId, number>();
  private clock: ReturnType<typeof setInterval> | undefined;
  private subscription: Subscription | undefined;

  protected readonly liveSeconds = computed(() => {
    const now = this.now();
    const live: Partial<Record<StepId, number>> = {};
    for (const step of this.steps()) {
      const started = this.stepStartedAt.get(step.id);
      if (step.status === 'running' && started !== undefined) {
        live[step.id] = (now - started) / 1000;
      }
    }
    return live;
  });

  protected readonly totalSeconds = computed(() =>
    this.loading() ? (this.now() - this.searchStartedAt) / 1000 : (this.response()?.timings.total_s ?? null),
  );

  protected readonly freshnessOptions: { value: Freshness | ''; label: string }[] = [
    { value: '', label: 'Any time' },
    { value: 'day', label: 'Past day' },
    { value: 'week', label: 'Past week' },
    { value: 'month', label: 'Past month' },
    { value: 'year', label: 'Past year' },
  ];
  protected readonly topKOptions = [3, 5, 8, 10];

  constructor() {
    this.destroyRef.onDestroy(() => this.stopClock());
  }

  protected onSubmit(event: Event): void {
    event.preventDefault();
    this.search();
  }

  protected search(): void {
    const query = this.queryText().trim();
    if (!query || this.loading()) {
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    this.response.set(null);
    this.steps.set([]);
    this.stepStartedAt.clear();
    this.startClock();

    this.subscription?.unsubscribe();
    this.subscription = this.api
      .searchStream({
        query,
        top_k: this.selectedTopK(),
        freshness: this.freshness() || null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (event) => this.onStreamEvent(event),
        error: (err: HttpErrorResponse) => {
          this.finish();
          this.error.set(
            err.status === 0 || err.status === 502 || err.status === 504
              ? `Cannot reach the web-search-agent at ${this.api.baseUrl} (:8201). Is the backend running?`
              : `Request failed (${err.status}): ${describeError(err)}`,
          );
        },
        complete: () => {
          if (this.loading()) {
            this.finish();
            this.error.set('The search ended without a result.');
          }
        },
      });
  }

  /** "Retry": send another request to the output agents with the saved run - no search, no LLM call. */
  protected retry(traceId: string): void {
    if (this.retrying()) {
      return;
    }
    this.retrying.set(true);
    this.error.set(null);
    this.api.retry(traceId).subscribe({
      next: (res) => {
        this.retrying.set(false);
        this.response.set(res);
        this.steps.set(res.steps);
        this.searched.emit(res);
      },
      error: (err: HttpErrorResponse) => {
        this.retrying.set(false);
        this.error.set(`Retry failed (${err.status}): ${describeError(err)}`);
      },
    });
  }

  private onStreamEvent(event: SearchStreamEvent): void {
    switch (event.type) {
      case 'steps':
        this.steps.set(event.steps);
        break;
      case 'step':
        // Parallel tasks (one per query / page) repeat "running" with progress; keep the first start time.
        if (event.step.status === 'running' && !this.stepStartedAt.has(event.step.id)) {
          this.stepStartedAt.set(event.step.id, Date.now());
        }
        this.steps.update((steps) => steps.map((s) => (s.id === event.step.id ? event.step : s)));
        break;
      case 'error':
        this.finish();
        this.steps.update((steps) =>
          steps.map((s) => (s.status === 'running' ? { ...s, status: 'failed', detail: event.error } : s)),
        );
        this.error.set(`The search failed: ${event.error}`);
        break;
      case 'result': {
        const res = event.result;
        this.finish();
        this.response.set(res);
        this.steps.set(res.steps);
        this.searched.emit(res);
        window.dispatchEvent(new CustomEvent(WEB_SEARCH_RESULT_EVENT, { detail: res }));
        break;
      }
    }
  }

  private finish(): void {
    this.loading.set(false);
    this.stopClock();
  }

  private startClock(): void {
    this.stopClock();
    this.searchStartedAt = Date.now();
    this.now.set(this.searchStartedAt);
    this.clock = setInterval(() => this.now.set(Date.now()), CLOCK_TICK_MS);
  }

  private stopClock(): void {
    if (this.clock !== undefined) {
      clearInterval(this.clock);
      this.clock = undefined;
    }
  }

  protected setFreshness(value: string): void {
    this.freshness.set(value as Freshness | '');
  }

}

function describeError(err: HttpErrorResponse): string {
  // The stream endpoint is requested as text, so FastAPI's JSON error arrives as a string.
  if (typeof err.error === 'string') {
    try {
      const detail = JSON.parse(err.error).detail;
      return detail ? JSON.stringify(detail) : err.message;
    } catch {
      return err.error || err.message;
    }
  }
  return err.error?.detail ? JSON.stringify(err.error.detail) : err.message;
}
