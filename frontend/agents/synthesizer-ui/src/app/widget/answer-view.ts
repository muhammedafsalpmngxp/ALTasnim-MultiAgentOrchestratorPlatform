import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { AgentOutput } from '@altasnim/shared';

import { renderMarkdown, withoutCitations } from '../markdown';

/** How a synthesizer result looks inside Multi Agent Flow / Runs. */
@Component({
  selector: 'alt-answer-view',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<div class="answer" [innerHTML]="html()"></div>`,
  styles: `
    .answer { font-size: 13.5px; line-height: 1.6; margin: 6px 0; }
    .answer ::ng-deep p { margin: 0 0 6px; }
    .answer ::ng-deep :is(ul, ol) { margin: 0 0 6px; padding-left: 18px; }
  `,
})
export class AnswerView {
  readonly result = input<AgentOutput | null>(null);
  protected readonly html = computed(() => {
    const r = this.result();
    return renderMarkdown(withoutCitations(String(r?.['answer'] ?? r?.summary ?? '')));
  });
}
