import { JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, ElementRef, input, signal, viewChild } from '@angular/core';

import { NextAgentResult, RetrievedChunk, RetrieveResponse, errorText, request, stream } from './api';
import { markdownToHtml } from './format';
import { ProgressSteps, RETRIEVE_STEPS, Step, applyEvent, failSteps, seconds } from './progress';

type NextResult = NextAgentResult & { retrying?: boolean };

interface Turn {
  question: string;
  chunks?: RetrievedChunk[];
  next?: NextResult[];
  error?: string;
  steps?: Step[]; // the live pipeline (POST /retrieve/stream)
  done?: boolean;
  ms?: number;
  showSteps?: boolean; // unfolded again after it finished
}

/** The answer text in a next agent's reply: a string, or its answer / summary field (also inside "result"). */
function answerText(response: unknown): string | null {
  if (typeof response === 'string') return response.trim() || null;
  if (response && typeof response === 'object') {
    const reply = response as Record<string, unknown>;
    for (const key of ['answer', 'summary', 'text', 'message']) {
      const value = reply[key];
      if (typeof value === 'string' && value.trim()) return value.trim();
    }
    if (reply['result']) return answerText(reply['result']);
  }
  return null;
}

/**
 * Chat window: each question goes to POST /retrieve/stream, which reports every step live (an animated pipeline).
 * The reply shows each next agent's answer, with the retrieved chunks as its sources (shown as soon as they are
 * ranked); a next agent that failed can be retried.
 */
@Component({
  selector: 'alt-retrieval-chat',
  imports: [JsonPipe, ProgressSteps],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="chat" [class.empty]="!turns().length">
      <header class="top">
        <span class="title">Ask your documents</span>
        <span class="sub">Hybrid search · rerank</span>
        @if (turns().length) {
          <button class="pill new" type="button" [disabled]="busy()" (click)="turns.set([])">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>
            New chat
          </button>
        }
      </header>

      <div class="scroll" #log>
        <div class="thread">
          @for (t of turns(); track $index; let ti = $index) {
            <div class="user"><div class="bubble">{{ t.question }}</div></div>

            <div class="assistant">
              <div class="avatar">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l9 5-9 5-9-5 9-5z" /><path d="M3 13l9 5 9-5" /></svg>
              </div>
              <div class="body">
                @if (t.steps?.length) {
                  @if (t.done) {
                    <button class="worked" type="button" [class.failed]="!!t.error" [attr.aria-expanded]="!!t.showSteps" (click)="toggleSteps(ti)">
                      @if (t.error) {
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16h.01" /></svg>
                        Stopped after {{ time(t.ms) }}
                      } @else {
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7" /></svg>
                        Searched your documents in {{ time(t.ms) }}
                      }
                      <svg class="chevron" [class.up]="t.showSteps" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6" /></svg>
                    </button>
                  }
                  <alt-progress-steps [steps]="t.steps!" [open]="!t.done || !!t.showSteps" />
                } @else if (!t.done) {
                  <div class="thinking"><span></span><span></span><span></span> Connecting…</div>
                } @else if (t.error) {
                  <div class="alert">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16h.01" /></svg>
                    <div class="alert-text">{{ t.error }}</div>
                  </div>
                }

                @for (n of t.next ?? []; track n.endpoint) {
                  @if (n.error) {
                    <div class="alert">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16h.01" /></svg>
                      <div class="alert-text">
                        <strong>{{ n.endpoint }}</strong> didn't answer{{ n.url ? ' (' + host(n.url) + ')' : '' }}
                        <div class="why">{{ n.error }}</div>
                      </div>
                      <button class="pill" type="button" [disabled]="n.retrying" (click)="retry(ti, n.endpoint)">
                        <svg [class.spin]="n.retrying" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7L21 8" /><path d="M21 3v5h-5" /></svg>
                        {{ n.retrying ? 'Retrying…' : 'Retry' }}
                      </button>
                    </div>
                  } @else {
                    @let text = answer(n.response);
                    @if (text) {
                      <div class="answer" [innerHTML]="html(text)"></div>
                    }
                    <div class="actions">
                      @if (text) {
                        <button class="icon-btn" type="button" [title]="copied() === ti + n.endpoint ? 'Copied' : 'Copy'" (click)="copy(text, ti + n.endpoint)">
                          @if (copied() === ti + n.endpoint) {
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7" /></svg>
                          } @else {
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></svg>
                          }
                        </button>
                      }
                      <span class="via">{{ n.endpoint }} · {{ host(n.url) }}</span>
                      <details class="raw">
                        <summary>Raw response</summary>
                        <pre>{{ n.response | json }}</pre>
                      </details>
                    </div>
                  }
                }

                @if (t.chunks; as chunks) {
                  @if (chunks.length) {
                    @if (t.done && !t.next?.length) {
                      <p class="lead">The most relevant passages in your documents:</p>
                    }
                    <details class="sources" [open]="!!t.done && !hasAnswer(t)">
                      <summary>
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /></svg>
                        {{ chunks.length }} {{ chunks.length === 1 ? 'source' : 'sources' }}
                        <span class="docs">· {{ documentNames(chunks) }}</span>
                        <svg class="chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6" /></svg>
                      </summary>
                      <ol>
                        @for (c of chunks; track c.id; let i = $index) {
                          <li class="source">
                            <div class="source-head">
                              <span class="num">{{ i + 1 }}</span>
                              <span class="doc-name">{{ c.document_name }}</span>
                              @if (c.page) {
                                <span>p. {{ c.page }}</span>
                              }
                              <span class="score" title="Reranker relevance, 0 to 1">relevance {{ relevance(c.score) }}</span>
                            </div>
                            <div class="source-text">{{ c.content }}</div>
                          </li>
                        }
                      </ol>
                    </details>
                  } @else if (t.done) {
                    <p class="lead">Nothing in your documents matches this question. Ingest some documents first.</p>
                  }
                }
              </div>
            </div>
          }
        </div>
      </div>

      @if (!turns().length) {
        <div class="hero">
          <h1>What do you want to know?</h1>
          <p>
            {{ documents() ? 'Answers come from your ' + documents() + ' ingested ' + (documents() === 1 ? 'document.' : 'documents.') : 'Ingest files on the left, then ask a question about them.' }}
          </p>
        </div>
      }

      <div class="composer-wrap">
        <form class="composer" (submit)="$event.preventDefault(); send()">
          <textarea
            #box
            rows="1"
            aria-label="Question"
            placeholder="Ask anything about your documents"
            [value]="draft()"
            (input)="type(box)"
            (keydown.enter)="enter($any($event))"
          ></textarea>
          <button class="send" type="submit" aria-label="Send" [disabled]="busy() || !draft().trim()">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
          </button>
        </form>
        @if (!turns().length && documents()) {
          <div class="suggestions">
            @for (s of suggestions; track s) {
              <button class="pill chip" type="button" (click)="ask(s)">{{ s }}</button>
            }
          </div>
        }
        <p class="hint">Answers are built only from your ingested documents. Check important details in the sources.</p>
      </div>
    </section>
  `,
  styles: `
    :host { display: flex; min-width: 0; min-height: 0; background: var(--r-bg); color: var(--r-text); }
    .chat { flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
    .top { display: flex; align-items: center; gap: 10px; height: 56px; flex: none; padding: 0 20px; }
    .title { font-size: 16px; font-weight: 600; }
    .sub { font-size: 13px; color: var(--r-faint); }
    .new { margin-left: auto; }
    .scroll { flex: 1; min-height: 0; overflow-y: auto; scrollbar-width: thin; scrollbar-color: var(--r-border) transparent; }
    .thread { display: flex; flex-direction: column; gap: 28px; max-width: 768px; margin: 0 auto; padding: 8px 24px 32px; }

    .user { display: flex; justify-content: flex-end; }
    .bubble {
      max-width: 75%; padding: 10px 18px; border-radius: 22px; background: var(--r-bubble);
      font-size: 15px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere;
    }
    .assistant { display: flex; align-items: flex-start; gap: 16px; }
    .avatar {
      display: grid; place-items: center; flex: none; width: 30px; height: 30px; margin-top: 1px;
      border: 1px solid var(--r-border); border-radius: 50%; color: var(--r-text);
    }
    .body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 12px; font-size: 15px; line-height: 1.7; }
    .answer { overflow-wrap: anywhere; }
    .answer ::ng-deep p { margin: 0 0 12px; }
    .answer ::ng-deep p:last-child { margin-bottom: 0; }
    .answer ::ng-deep ul, .answer ::ng-deep ol { margin: 0 0 12px; padding-left: 22px; }
    .answer ::ng-deep li { margin: 4px 0; }
    .answer ::ng-deep strong { font-weight: 600; }
    .answer ::ng-deep code { padding: 1px 6px; border-radius: 6px; background: var(--r-bubble); font-size: 13px; }
    .lead { margin: 0; }
    .worked {
      display: inline-flex; align-items: center; gap: 7px; align-self: flex-start; padding: 2px 0;
      font: inherit; font-size: 13px; color: var(--r-muted); background: none; border: 0; cursor: pointer;
    }
    .worked:hover { color: var(--r-text); }
    .worked.failed > svg:first-child { color: var(--r-danger); }
    .worked .chevron { transition: transform 0.2s ease; }
    .worked .chevron.up { transform: rotate(180deg); }
    .body > alt-progress-steps { transition: margin-top 0.45s ease; }
    .body > alt-progress-steps:not(.open) { margin-top: -12px; }
    .bubble, .worked, .answer, .actions, .alert, .sources, .lead { animation: rise 0.4s ease both; }
    @keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
    @media (prefers-reduced-motion: reduce) { .bubble, .worked, .answer, .actions, .alert, .sources, .lead { animation: none; } }

    .actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: -4px; font-size: 12px; color: var(--r-faint); }
    .raw summary { cursor: pointer; list-style: none; text-decoration: underline; text-underline-offset: 2px; }
    .raw summary::-webkit-details-marker { display: none; }
    .raw pre {
      max-height: 16em; overflow: auto; margin: 8px 0 0; padding: 12px; border-radius: 10px;
      background: var(--r-bubble); color: var(--r-text); white-space: pre-wrap;
    }
    .raw[open] { flex-basis: 100%; }

    .alert { display: flex; align-items: flex-start; gap: 10px; padding: 12px 14px; border: 1px solid var(--r-border); border-radius: 14px; font-size: 14px; line-height: 1.5; }
    .alert > svg { flex: none; margin-top: 1px; color: var(--r-danger); }
    .alert-text { flex: 1; min-width: 0; overflow-wrap: anywhere; }
    .why { font-size: 13px; color: var(--r-muted); }

    .sources { border: 1px solid var(--r-border); border-radius: 14px; overflow: hidden; }
    .sources summary {
      display: flex; align-items: center; gap: 8px; padding: 10px 14px;
      font-size: 13px; font-weight: 500; cursor: pointer; list-style: none; user-select: none;
    }
    .sources summary::-webkit-details-marker { display: none; }
    .sources summary:hover { background: var(--r-hover); }
    .sources .docs { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 400; color: var(--r-faint); }
    .chevron { flex: none; color: var(--r-faint); transition: transform 0.15s; }
    .sources[open] .chevron { transform: rotate(180deg); }
    .sources ol { list-style: none; margin: 0; padding: 0; border-top: 1px solid var(--r-border); }
    .source { padding: 12px 14px; }
    .source + .source { border-top: 1px solid var(--r-border); }
    .source-head { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--r-faint); }
    .num {
      display: grid; place-items: center; width: 20px; height: 20px; border-radius: 50%;
      background: var(--r-bubble); color: var(--r-text); font-size: 11px; font-weight: 600;
    }
    .doc-name { font-weight: 600; color: var(--r-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .score { margin-left: auto; white-space: nowrap; }
    .source-text { max-height: 10.5em; overflow-y: auto; margin-top: 6px; font-size: 13px; line-height: 1.6; color: var(--r-muted); white-space: pre-wrap; }

    .thinking { display: flex; align-items: center; gap: 5px; color: var(--r-faint); font-size: 14px; }
    .thinking span { width: 7px; height: 7px; border-radius: 50%; background: var(--r-text); animation: pulse 1.2s infinite ease-in-out; }
    .thinking span:nth-child(2) { animation-delay: 0.15s; }
    .thinking span:nth-child(3) { animation-delay: 0.3s; margin-right: 6px; }
    @keyframes pulse { 0%, 80%, 100% { opacity: 0.25; transform: scale(0.8); } 40% { opacity: 1; transform: scale(1); } }
    .spin { animation: spin 0.8s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }

    .pill {
      display: inline-flex; align-items: center; gap: 6px; flex: none; padding: 6px 14px;
      font: inherit; font-size: 13px; font-weight: 500; white-space: nowrap; cursor: pointer;
      color: var(--r-text); background: var(--r-bg); border: 1px solid var(--r-border); border-radius: 999px;
    }
    .pill:hover:not(:disabled) { background: var(--r-hover); }
    .pill:disabled { cursor: default; color: var(--r-faint); }
    .icon-btn {
      display: grid; place-items: center; width: 28px; height: 28px;
      color: var(--r-muted); background: transparent; border: 0; border-radius: 8px; cursor: pointer;
    }
    .icon-btn:hover { background: var(--r-hover); color: var(--r-text); }

    .hero { margin-top: auto; padding: 0 24px 28px; text-align: center; }
    .hero h1 { margin: 0 0 8px; font-size: 28px; font-weight: 600; letter-spacing: -0.01em; }
    .hero p { margin: 0; color: var(--r-muted); }
    .chat.empty .scroll { flex: 0; }
    .chat.empty .composer-wrap { margin-bottom: auto; }

    .composer-wrap { flex: none; width: 100%; max-width: 768px; margin: 0 auto; padding: 0 24px 14px; }
    .composer {
      display: flex; align-items: flex-end; gap: 8px; padding: 10px 10px 10px 20px;
      background: var(--r-bg); border: 1px solid var(--r-border); border-radius: 26px;
      box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
    }
    .composer:focus-within { border-color: var(--r-faint); }
    textarea {
      flex: 1; min-width: 0; max-height: 200px; padding: 6px 0; resize: none;
      font: inherit; font-size: 15px; line-height: 24px; color: var(--r-text); background: transparent; border: 0; outline: 0;
    }
    textarea::placeholder { color: var(--r-faint); }
    .send {
      display: grid; place-items: center; flex: none; width: 36px; height: 36px;
      color: var(--r-on-accent); background: var(--r-accent); border: 0; border-radius: 50%; cursor: pointer;
    }
    .send:disabled { color: var(--r-bg); background: var(--r-border); cursor: default; }
    .suggestions { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-top: 16px; }
    .chip { color: var(--r-muted); font-weight: 400; }
    .hint { margin: 10px 0 0; text-align: center; font-size: 12px; color: var(--r-faint); }
  `,
})
export class RetrievalChat {
  /** How many documents are ingested (shown in the empty chat). */
  readonly documents = input(0);

  protected readonly turns = signal<Turn[]>([]);
  protected readonly draft = signal('');
  protected readonly busy = signal(false);
  protected readonly copied = signal<string | null>(null);
  protected readonly suggestions = ['Summarize the key points', 'What are the main requirements?', 'List the important dates and amounts'];
  protected readonly answer = answerText;
  protected readonly html = markdownToHtml;
  protected readonly time = seconds;
  private readonly log = viewChild<ElementRef<HTMLElement>>('log');
  private readonly box = viewChild<ElementRef<HTMLTextAreaElement>>('box');

  protected async send(): Promise<void> {
    const question = this.draft().trim();
    if (!question || this.busy()) return;
    this.draft.set('');
    this.resize();
    this.busy.set(true);
    this.turns.update((turns) => [...turns, { question, steps: [] }]);
    this.scrollToEnd();

    const turn = this.turns().length - 1;
    const started = performance.now();
    try {
      const res = await stream<RetrieveResponse>(
        '/retrieve/stream',
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question }) },
        (event) => {
          this.patch(turn, (t) => ({
            ...t,
            steps: applyEvent(t.steps ?? [], event, RETRIEVE_STEPS),
            ...(event.chunks ? { chunks: event.chunks } : {}),
          }));
          if (event.chunks) this.scrollToEnd();
        },
      );
      this.patch(turn, (t) => ({ ...t, chunks: res.chunks, next: res.next_agents, done: true, ms: performance.now() - started }));
    } catch (err) {
      const error = errorText(err);
      const ms = performance.now() - started;
      this.patch(turn, (t) => ({ ...t, error, steps: failSteps(t.steps ?? [], error), done: true, showSteps: true, ms }));
    }
    this.busy.set(false);
    this.scrollToEnd();
  }

  protected ask(question: string): void {
    this.draft.set(question);
    void this.send();
  }

  /** Enter sends, Shift+Enter adds a line. */
  protected enter(event: KeyboardEvent): void {
    if (event.shiftKey || event.isComposing) return;
    event.preventDefault();
    void this.send();
  }

  protected type(box: HTMLTextAreaElement): void {
    this.draft.set(box.value);
    this.resize();
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

  protected async copy(text: string, key: string): Promise<void> {
    await navigator.clipboard.writeText(text);
    this.copied.set(key);
    setTimeout(() => this.copied.update((k) => (k === key ? null : k)), 1500);
  }

  protected hasAnswer(t: Turn): boolean {
    return !!t.next?.some((n) => !n.error && answerText(n.response));
  }

  /** 0.93 -> "0.93", 0.0034 -> "0.0034" (vague questions score very low; never shown as 0). */
  protected relevance(score: number): string {
    return score >= 0.01 ? score.toFixed(2) : score.toPrecision(2);
  }

  protected documentNames(chunks: RetrievedChunk[]): string {
    const names = [...new Set(chunks.map((c) => c.document_name))];
    return names.length > 2 ? `${names.slice(0, 2).join(', ')} +${names.length - 2}` : names.join(', ');
  }

  protected host(url: string | null): string {
    try {
      return url ? new URL(url).host : '';
    } catch {
      return url ?? '';
    }
  }

  protected toggleSteps(turn: number): void {
    this.patch(turn, (t) => ({ ...t, showSteps: !t.showSteps }));
  }

  private patch(turn: number, change: (t: Turn) => Turn): void {
    this.turns.update((turns) => turns.map((t, i) => (i === turn ? change(t) : t)));
  }

  private updateNext(turn: number, endpoint: string, change: (n: NextResult) => NextResult): void {
    this.patch(turn, (t) => ({ ...t, next: t.next?.map((n) => (n.endpoint === endpoint ? change(n) : n)) }));
  }

  /** Grows the box with its text, up to 200px. */
  private resize(): void {
    setTimeout(() => {
      const el = this.box()?.nativeElement;
      if (!el) return;
      el.style.height = 'auto';
      el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
    });
  }

  private scrollToEnd(): void {
    setTimeout(() => {
      const el = this.log()?.nativeElement;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }
}
