import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { AgentOutput } from '@altasnim/shared';

import { toStepResult } from '../web-search/web-search.models';

/**
 * How a web_search step looks inside Multi Agent Flow / Runs (loaded by the platform via './Widget'):
 * the question and the top 3 contents - exactly what the verifier receives.
 */
@Component({
  selector: 'alt-search-result-view',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (view(); as r) {
      <div class="question"><span class="muted">Question</span> {{ r.question }}</div>
      @if (r.findings.length) {
        <ol class="top">
          @for (f of r.findings; track f.rank) {
            <li>
              <a [href]="f.url" target="_blank" rel="noopener noreferrer">[{{ f.rank }}] {{ f.title }}</a>
              <span class="domain muted">{{ domain(f.url) }}</span>
              <p [class.clamped]="!expanded().has(f.rank)">{{ f.content }}</p>
              @if (f.content.length > clampChars) {
                <button type="button" class="more" (click)="toggle(f.rank)">
                  {{ expanded().has(f.rank) ? 'Show less' : 'Show more' }}
                </button>
              }
            </li>
          }
        </ol>
      } @else {
        <p class="muted">{{ r.summary || 'No findings' }}</p>
      }
    }
  `,
  styles: `
    :host { display: block; margin: 6px 0; }
    .question { margin-bottom: 8px; font-weight: 600; }
    .question .muted { font-weight: 400; font-size: 12px; margin-right: 6px; }
    .top { display: flex; flex-direction: column; gap: 10px; margin: 0; padding: 0; list-style: none; }
    .top li { padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface); }
    .top a { font-weight: 600; text-decoration: none; overflow-wrap: anywhere; }
    .top a:hover { text-decoration: underline; }
    .domain { margin-left: 6px; font-size: 12px; }
    p { margin: 6px 0 0; line-height: 1.5; font-size: 13px; }
    .clamped { display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
    .more { padding: 0; border: 0; background: none; color: var(--primary); font: inherit; font-size: 12px; cursor: pointer; }
  `,
})
export class SearchResultView {
  readonly result = input<AgentOutput | null>(null);
  protected readonly view = computed(() => toStepResult(this.result()));
  protected readonly expanded = signal(new Set<number>());
  /** About three lines of the clamped paragraph. */
  protected readonly clampChars = 240;

  protected toggle(rank: number): void {
    this.expanded.update((open) => {
      const next = new Set(open);
      if (!next.delete(rank)) {
        next.add(rank);
      }
      return next;
    });
  }

  protected domain(url: string): string {
    try {
      return new URL(url).hostname.replace(/^www\./, '');
    } catch {
      return '';
    }
  }
}
