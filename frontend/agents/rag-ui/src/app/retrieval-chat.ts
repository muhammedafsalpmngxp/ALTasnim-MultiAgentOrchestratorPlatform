import { JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, ElementRef, signal, viewChild } from '@angular/core';

import { NextAgentResult, RetrievedChunk, RetrieveResponse, errorText, request } from './api';

type NextResult = NextAgentResult & { retrying?: boolean };

interface Turn {
  question: string;
  chunks?: RetrievedChunk[];
  next?: NextResult[];
  error?: string;
}

/** Chat window: each question is sent to POST /retrieve and answered with the retrieved chunks. */
@Component({
  selector: 'alt-retrieval-chat',
  imports: [JsonPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="card chat">
      <h2>Ask your documents</h2>
      <p class="muted">Shows the chunks retrieved for each question (hybrid search + rerank) and what the next agents did with them.</p>

      <div class="log" #log>
        @for (t of turns(); track $index; let ti = $index) {
          <div class="question">{{ t.question }}</div>
          @if (t.error) {
            <p class="error">{{ t.error }}</p>
          } @else if (!t.chunks) {
            <p class="muted">Retrieving…</p>
          } @else {
            @for (c of t.chunks; track c.id; let i = $index) {
              <div class="chunk">
                <div class="meta">
                  <span class="muted">#{{ i + 1 }}</span>
                  <strong>{{ c.document_name }}</strong>
                  @if (c.page) {
                    <span class="muted">page {{ c.page }}</span>
                  }
                  <span class="score" title="Reranker relevance (0-1)">{{ c.score.toFixed(2) }}</span>
                </div>
                <div class="content">{{ c.content }}</div>
              </div>
            } @empty {
              <p class="muted">No chunks found. Ingest some documents first.</p>
            }
            @for (n of t.next; track n.endpoint) {
              @if (n.error) {
                <div class="failed">
                  <p class="error">{{ n.endpoint }} ({{ n.url ?? 'not found' }}) failed: {{ n.error }}</p>
                  <button class="btn btn-sm" type="button" [disabled]="n.retrying" (click)="retry(ti, n.endpoint)">
                    {{ n.retrying ? 'Retrying…' : 'Retry' }}
                  </button>
                </div>
              } @else {
                <details class="next">
                  <summary>Passed to {{ n.endpoint }} · {{ n.url }} · HTTP {{ n.status }}</summary>
                  <pre>{{ n.response | json }}</pre>
                </details>
              }
            }
          }
        } @empty {
          <p class="muted">Ask a question about the ingested documents.</p>
        }
      </div>

      <form class="row" (submit)="$event.preventDefault(); send()">
        <input
          class="input"
          placeholder="e.g. What is the retention money?"
          [value]="draft()"
          (input)="draft.set($any($event.target).value)"
          [disabled]="busy()"
        />
        <button class="btn btn-primary" type="submit" [disabled]="busy() || !draft().trim()">Send</button>
      </form>
    </div>
  `,
  styles: `
    .chat { display: flex; flex-direction: column; }
    .log { display: flex; flex-direction: column; gap: 8px; min-height: 240px; max-height: 60vh; overflow-y: auto; margin: 8px 0 12px; }
    .question { align-self: flex-end; max-width: 80%; background: var(--primary); color: #fff; padding: 8px 12px; border-radius: var(--radius); }
    .chunk { border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-2); padding: 8px 10px; }
    .meta { display: flex; gap: 8px; align-items: baseline; font-size: 12px; }
    .score { margin-left: auto; padding: 0 8px; border-radius: 999px; background: var(--ok-soft); color: var(--ok); font-weight: 600; }
    .content { white-space: pre-wrap; font-size: 13px; max-height: 9em; overflow-y: auto; margin-top: 4px; }
    .error { color: var(--danger); }
    .failed { display: flex; gap: 8px; align-items: center; }
    .failed .error { flex: 1; margin: 0; }
    .next summary { cursor: pointer; font-size: 12px; color: var(--ok); }
    .next pre { white-space: pre-wrap; max-height: 12em; overflow-y: auto; margin: 4px 0 0; }
    form .input { flex: 1; width: auto; }
  `,
})
export class RetrievalChat {
  protected readonly turns = signal<Turn[]>([]);
  protected readonly draft = signal('');
  protected readonly busy = signal(false);
  private readonly log = viewChild<ElementRef<HTMLElement>>('log');

  protected async send(): Promise<void> {
    const question = this.draft().trim();
    if (!question || this.busy()) return;
    this.draft.set('');
    this.busy.set(true);
    this.turns.update((turns) => [...turns, { question }]);
    this.scrollToEnd();

    let answer: Partial<Turn>;
    try {
      const res = await request<RetrieveResponse>('/retrieve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      });
      answer = { chunks: res.chunks, next: res.next_agents };
    } catch (err) {
      answer = { error: errorText(err) };
    }
    this.turns.update((turns) => turns.map((t, i) => (i === turns.length - 1 ? { ...t, ...answer } : t)));
    this.busy.set(false);
    this.scrollToEnd();
  }

  /** Sends this turn's question + chunks again to one next agent that failed (POST /next-agents/retry). */
  protected async retry(turn: number, endpoint: string): Promise<void> {
    const t = this.turns()[turn];
    if (!t.chunks) return;
    this.updateNext(turn, endpoint, (n) => ({ ...n, retrying: true }));
    try {
      const result = await request<NextAgentResult>('/next-agents/retry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ endpoint, question: t.question, chunks: t.chunks }),
      });
      this.updateNext(turn, endpoint, () => result);
    } catch (err) {
      this.updateNext(turn, endpoint, (n) => ({ ...n, retrying: false, error: errorText(err) }));
    }
  }

  private updateNext(turn: number, endpoint: string, change: (n: NextResult) => NextResult): void {
    this.turns.update((turns) =>
      turns.map((t, i) => (i === turn ? { ...t, next: t.next?.map((n) => (n.endpoint === endpoint ? change(n) : n)) } : t)),
    );
  }

  private scrollToEnd(): void {
    setTimeout(() => {
      const el = this.log()?.nativeElement;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }
}
