import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';

import { formatSeconds } from '../format';
import { PipelineStep, StepId, StepStatus } from '../web-search.models';

const STATUS_LABEL: Record<StepStatus, string> = {
  pending: 'Waiting',
  running: 'Running',
  done: 'Done',
  skipped: 'Skipped',
  failed: 'Failed',
};

/** The backend processing flow as connected boxes: Planner → Search → Extract → … with seconds per step. */
@Component({
  selector: 'alt-ws-pipeline-flow',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './pipeline-flow.html',
  styleUrl: './pipeline-flow.css',
})
export class PipelineFlow {
  readonly steps = input.required<PipelineStep[]>();
  /** Live seconds for steps that are still running (computed by the parent from its clock). */
  readonly liveSeconds = input<Partial<Record<StepId, number>>>({});
  readonly totalSeconds = input<number | null>(null);
  readonly running = input(false);
  /** Show "Retry" on the Send output step (the run is saved). */
  readonly retryable = input(false);
  readonly retrying = input(false);
  /** "Retry" clicked: send another request to the output agents. */
  readonly retry = output<void>();

  /** null = follow the pipeline (running step, else the last one that ran). */
  private readonly pinned = signal<StepId | null>(null);

  protected readonly selected = computed<PipelineStep | undefined>(() => {
    const steps = this.steps();
    const pinned = this.pinned();
    return (
      steps.find((s) => s.id === pinned) ??
      steps.find((s) => s.status === 'running') ??
      [...steps].reverse().find((s) => s.status === 'done' || s.status === 'failed')
    );
  });

  protected readonly doneCount = computed(
    () => this.steps().filter((s) => s.status !== 'pending' && s.status !== 'running').length,
  );

  protected readonly percent = computed(() => {
    const total = this.steps().length;
    return total ? Math.round((this.doneCount() / total) * 100) : 0;
  });

  /** Colours the total timer and progress bar: amber while running, then green or red. */
  protected readonly outcome = computed<'running' | 'success' | 'failed'>(() => {
    if (this.running()) {
      return 'running';
    }
    return this.steps().some((s) => s.status === 'failed') ? 'failed' : 'success';
  });

  protected readonly formatSeconds = formatSeconds;

  protected label(status: StepStatus): string {
    return STATUS_LABEL[status];
  }

  protected seconds(step: PipelineStep): string {
    if (step.status === 'running') {
      return formatSeconds(this.liveSeconds()[step.id] ?? 0);
    }
    return formatSeconds(step.duration_s);
  }

  /** A connector takes the state of the step it leads into; "active" shows a comet travelling along it. */
  protected linkState(next: PipelineStep): 'active' | 'done' | 'failed' | 'skipped' | 'idle' {
    switch (next.status) {
      case 'running':
        return 'active';
      case 'pending':
        return 'idle';
      default:
        return next.status;
    }
  }

  protected select(step: PipelineStep): void {
    this.pinned.set(this.pinned() === step.id ? null : step.id);
  }

  protected isSelected(step: PipelineStep): boolean {
    return this.selected()?.id === step.id;
  }
}
