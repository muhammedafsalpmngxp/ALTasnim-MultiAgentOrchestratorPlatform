import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { AgentOutput } from '@altasnim/shared';

interface Finding {
  title: string;
  url: string;
  snippet: string;
  query: string;
}

/** How a web_search result looks inside Multi Agent Flow / Runs (loaded by the platform via './Widget'). */
@Component({
  selector: 'alt-search-result-view',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <ul class="findings">
      @for (f of findings(); track f.url) {
        <li>
          <a [href]="f.url" target="_blank" rel="noopener">{{ f.title }}</a>
          <div class="muted">{{ f.snippet }}</div>
        </li>
      } @empty {
        <li class="muted">{{ result()?.summary ?? 'No findings' }}</li>
      }
    </ul>
  `,
  styles: `
    .findings { margin: 6px 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; }
    .findings .muted { font-size: 12px; }
  `,
})
export class SearchResultView {
  readonly result = input<AgentOutput | null>(null);
  protected readonly findings = computed(() => (this.result()?.['findings'] as Finding[] | undefined) ?? []);
}
