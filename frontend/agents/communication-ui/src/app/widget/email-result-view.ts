import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { AgentOutput } from '@altasnim/shared';

/** How a communication result looks inside Multi Agent Flow / Runs. */
@Component({
  selector: 'alt-email-result-view',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (sent()) {
      <div class="sent">
        <span class="icon" aria-hidden="true">✉</span>
        <div>
          <div><strong>{{ result()?.['subject'] }}</strong></div>
          <div class="muted small">
            {{ logged() ? 'logged only (test mode), not delivered to' : 'sent to' }} {{ recipients() }}
            @if (cc()) {
              · cc {{ cc() }}
            }
            · {{ writerText() }}
          </div>
        </div>
      </div>
    } @else {
      <p class="muted">{{ result()?.summary }}</p>
    }
  `,
  styles: `
    .sent { display: flex; gap: 10px; align-items: center; margin: 6px 0; }
    .icon { font-size: 20px; color: var(--ok); }
    .small { font-size: 12px; }
  `,
})
export class EmailResultView {
  readonly result = input<AgentOutput | null>(null);
  protected readonly sent = computed(() => this.result()?.['delivery'] === 'sent');
  protected readonly logged = computed(() => this.result()?.['channel'] === 'console');
  protected readonly recipients = computed(() => ((this.result()?.['to'] as string[] | undefined) ?? []).join(', '));
  protected readonly cc = computed(() => ((this.result()?.['cc'] as string[] | undefined) ?? []).join(', '));
  protected readonly writerText = computed(() => {
    const writer = this.result()?.['writer'];
    return writer === 'llm' ? 'written by the LLM' : writer === 'user' ? 'your own text' : 'written from a template';
  });
}
