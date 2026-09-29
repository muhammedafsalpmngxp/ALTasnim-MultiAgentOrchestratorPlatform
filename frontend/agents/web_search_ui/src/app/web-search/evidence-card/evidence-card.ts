import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';

import { formatDate } from '../format';
import { Evidence } from '../web-search.models';

const PREVIEW_CHARS = 420;

@Component({
  selector: 'alt-ws-evidence-card',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './evidence-card.html',
  styleUrl: './evidence-card.css',
})
export class EvidenceCard {
  readonly evidence = input.required<Evidence>();

  protected readonly expanded = signal(false);
  protected readonly isLong = computed(() => this.evidence().content.length > PREVIEW_CHARS);
  protected readonly text = computed(() => {
    const content = this.evidence().content;
    return this.expanded() || !this.isLong() ? content : `${content.slice(0, PREVIEW_CHARS).trimEnd()}…`;
  });
  protected readonly relevancePct = computed(() => Math.round(this.evidence().relevance_score * 100));
  protected readonly date = computed(() => formatDate(this.evidence().published_date));
}
