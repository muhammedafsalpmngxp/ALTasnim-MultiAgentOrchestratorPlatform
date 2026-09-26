import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { AgentOutput } from '@altasnim/shared';

/** How a verifier result looks inside Multi Agent Flow / Runs. */
@Component({
  selector: 'alt-verdict-view',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="verdict" [class.passed]="passed()">
      {{ passed() ? '✓ Verification passed' : '✗ Verification failed' }}
    </div>
    @if (issues().length) {
      <ul class="issues">
        @for (i of issues(); track i) {
          <li>{{ i }}</li>
        }
      </ul>
    }
    @if (warnings().length) {
      <ul class="warnings">
        @for (w of warnings(); track w) {
          <li>{{ w }}</li>
        }
      </ul>
    }
  `,
  styles: `
    .verdict { font-weight: 600; color: var(--danger); margin: 6px 0; }
    .verdict.passed { color: var(--ok); }
    ul { margin: 4px 0; padding-left: 18px; font-size: 12px; }
    .issues { color: var(--danger); }
    .warnings { color: var(--warn); }
  `,
})
export class VerdictView {
  readonly result = input<AgentOutput | null>(null);
  protected readonly passed = computed(() => this.result()?.['passed'] === true);
  protected readonly issues = computed(() => (this.result()?.['issues'] as string[] | undefined) ?? []);
  protected readonly warnings = computed(() => (this.result()?.['warnings'] as string[] | undefined) ?? []);
}
