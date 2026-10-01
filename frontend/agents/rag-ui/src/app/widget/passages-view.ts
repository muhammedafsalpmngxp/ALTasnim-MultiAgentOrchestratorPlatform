import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { AgentOutput } from '@altasnim/shared';

interface Chunk {
  id?: string;
  document_name?: string;
  page?: number | null;
  chunk_index?: number;
  score?: number;
  content?: string;
}

const PREVIEW = 260;

/** How a rag result looks inside Runs / Multi Agent Flow: the passages it found, best first. */
@Component({
  selector: 'alt-rag-passages',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (chunks().length) {
      <ol class="passages">
        @for (c of chunks(); track c.id ?? $index; let i = $index) {
          <li>
            <div class="meta">
              <span class="doc" [title]="c.document_name ?? ''">{{ c.document_name ?? 'document' }}</span>
              @if (c.page != null) { <span class="faint">p. {{ c.page }}</span> }
              @if (c.score != null) {
                <span class="score" [title]="'relevance ' + c.score"><i [style.width.%]="c.score * 100"></i></span>
              }
            </div>
            <p class="text">{{ isOpen(i) ? c.content : preview(c.content) }}</p>
            @if ((c.content?.length ?? 0) > previewChars) {
              <button class="more" type="button" (click)="toggle(i)">{{ isOpen(i) ? 'Show less' : 'Show more' }}</button>
            }
          </li>
        }
      </ol>
    } @else {
      <p class="none">{{ result()?.summary ?? 'No passage of the documents matches the question.' }}</p>
    }
  `,
  styles: `
    .passages { display: flex; flex-direction: column; gap: 8px; margin: 6px 0; padding: 0; list-style: none; counter-reset: p; }
    li { position: relative; padding: 8px 10px 8px 34px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface); }
    li::before { counter-increment: p; content: counter(p); position: absolute; left: 10px; top: 9px; width: 16px; height: 16px;
                 border-radius: 50%; font-size: 10px; font-weight: 700; line-height: 16px; text-align: center;
                 color: var(--primary); background: var(--primary-soft); }
    .meta { display: flex; align-items: center; gap: 8px; min-width: 0; font-size: 12px; }
    .doc { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .faint { color: var(--text-faint); white-space: nowrap; }
    .score { flex: none; width: 48px; height: 4px; margin-left: auto; border-radius: 999px; background: var(--surface-3); overflow: hidden; }
    .score i { display: block; height: 100%; background: var(--ok); }
    .text { margin: 4px 0 0; font-size: 12.5px; line-height: 1.5; color: var(--text-muted); white-space: pre-line; overflow-wrap: anywhere; }
    .more { padding: 0; margin-top: 2px; font: inherit; font-size: 12px; color: var(--primary); background: none; border: 0; cursor: pointer; }
    .none { margin: 6px 0; color: var(--text-muted); }
  `,
})
export class PassagesView {
  readonly result = input<AgentOutput | null>(null);
  protected readonly previewChars = PREVIEW;
  private readonly open = signal<ReadonlySet<number>>(new Set());

  protected readonly chunks = computed<Chunk[]>(() => {
    const chunks = this.result()?.['chunks'];
    return Array.isArray(chunks) ? (chunks as Chunk[]) : [];
  });

  protected preview(text = ''): string {
    return text.length > PREVIEW ? text.slice(0, PREVIEW).trimEnd() + '…' : text;
  }

  protected isOpen(i: number): boolean {
    return this.open().has(i);
  }

  protected toggle(i: number): void {
    this.open.update((set) => {
      const next = new Set(set);
      if (!next.delete(i)) next.add(i);
      return next;
    });
  }
}
