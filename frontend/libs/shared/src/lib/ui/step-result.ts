import { NgComponentOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, Type, effect, inject, input, signal } from '@angular/core';

import { AGENT_WIDGET_LOADER } from '../agent-widget';
import { AgentResult } from '../models';
import { JsonView } from './json-view';
import { StatusBadge } from './status-badge';

/** Shows one step's result with the owning team's widget (resultView), or a generic fallback. */
@Component({
  selector: 'alt-step-result',
  imports: [NgComponentOutlet, JsonView, StatusBadge],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="result">
      <div class="row">
        <code>{{ result().step_id }}</code>
        <strong>{{ result().agent }}</strong>
        <alt-status-badge [status]="result().status" />
      </div>
      @if (view(); as component) {
        <ng-container *ngComponentOutlet="component; inputs: { result: result().output }" />
      } @else {
        <p class="summary">{{ result().output.summary ?? result().error ?? '' }}</p>
      }
      <alt-json-view [value]="result().output" label="Raw output" />
    </div>
  `,
  styles: `
    .result { border-top: 1px solid var(--border); padding: 10px 0; }
    .summary { white-space: pre-wrap; margin: 6px 0; }
  `,
})
export class StepResult {
  readonly result = input.required<AgentResult>();
  private readonly loader = inject(AGENT_WIDGET_LOADER, { optional: true });
  protected readonly view = signal<Type<unknown> | null>(null);

  constructor() {
    effect(() => {
      const agent = this.result().agent;
      this.view.set(null);
      this.loader?.(agent).then((w) => this.view.set(w?.resultView ?? null));
    });
  }
}
