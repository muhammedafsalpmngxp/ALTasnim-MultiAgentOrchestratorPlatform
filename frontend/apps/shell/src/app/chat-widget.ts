import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  effect,
  inject,
  model,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { CurrentRun, DecisionPanel, markdownToHtml } from '@altasnim/shared';

const EXAMPLES = ['Who issues the pegging sheet?', 'What is the retention money?', 'What is the price of iPhone?'];
/** Who is working (shown in bold) and what they are doing; the phrases rotate while one agent takes a while. */
const WORK: Record<string, { who: string; say: string[] }> = {
  planning: { who: 'Supervisor', say: ['Thinking deeply…', 'Understanding your question…', 'Choosing the right agents…'] },
  replan: { who: 'Supervisor', say: ['That did not answer it, trying another way…', 'Choosing another source…'] },
  rag: { who: 'RAG', say: ['Searching your documents…', 'Reading the best passages…'] },
  web_search: { who: 'Web search', say: ['Searching the web…', 'Reading the sources…', 'Comparing what it found…'] },
  verifier: { who: 'Verifier', say: ['Checking the facts…', 'Making sure it answers your question…'] },
  synthesizer: { who: 'Synthesizer', say: ['Writing your answer…', 'Almost there…'] },
  finishing: { who: 'Supervisor', say: ['Putting your answer together…', 'Almost done…'] },
  communication: { who: 'Communication', say: ['Preparing the email…'] },
};
const PHRASE_MS = 2800;

/** A message's text (LangChain content is a string or a list of parts). */
function textOf(content: unknown): string {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content.map((p) => (typeof p === 'string' ? p : (p as { text?: string })?.text ?? '')).join('');
  }
  return content == null ? '' : JSON.stringify(content);
}

/**
 * The chat with the supervisor, on every page: a button at the bottom right that opens the chat as a right
 * sidebar (the shell's third column; the page makes room). It asks in the shared CurrentRun, so the Multi Agent
 * Flow page draws the same run live.
 */
@Component({
  selector: 'alt-chat-widget',
  imports: [DecisionPanel, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[class.open]': 'open()' },
  template: `
    @if (open()) {
      <section class="panel" role="complementary" aria-label="Chat with the assistant">
        <header>
          <span class="avatar" aria-hidden="true">◆</span>
          <div class="who">
            <strong>Assistant</strong>
            <span class="sub" [class.live]="running()">{{ statusText() }}</span>
          </div>
          <a class="icon" routerLink="/flow" title="See the flow of this chat">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /><path d="M10 6.5h4.5a2 2 0 0 1 2 2V14" /></svg>
          </a>
          <button class="icon" type="button" title="New chat" [disabled]="running()" (click)="current.newChat()">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>
          </button>
          <button class="icon" type="button" title="Close the chat" (click)="open.set(false)">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m13 6 6 6-6 6M5 6l6 6-6 6" /></svg>
          </button>
        </header>

        <div class="log" #log>
          @for (m of messages(); track $index) {
            @if (m.type === 'human') {
              <div class="msg human"><div class="bubble">{{ text(m.content) }}</div></div>
            } @else {
              <div class="msg ai"><div class="bubble answer reveal" [innerHTML]="html(text(m.content))"></div></div>
            }
          } @empty {
            <div class="hello">
              <p><strong>Hi!</strong> Ask me about your documents, or anything on the web. I plan which agents to use and show it live in Multi Agent Flow.</p>
              <div class="chips">
                @for (e of examples; track e) {
                  <button class="chip" type="button" (click)="send(e)">{{ e }}</button>
                }
              </div>
            </div>
          }
          @if (running()) {
            <div class="msg ai" animate.leave="fade-out">
              <div class="bubble working" role="status" aria-live="polite">
                <span class="wave" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>
                <span class="say">
                  @for (w of [work()]; track w.key) {
                    <span class="line" animate.enter="swap-in" animate.leave="swap-out"><strong>{{ w.who }}</strong><span class="shimmer">{{ w.text }}</span></span>
                  }
                </span>
              </div>
            </div>
          }
          @if (session().interrupt(); as pending) {
            <alt-decision-panel [payload]="pending" [busy]="running()" (decided)="decide($event)" />
          }
          @if (session().error(); as err) {
            <div class="error">{{ err }}</div>
          }
        </div>

        <form class="composer" (submit)="$event.preventDefault(); send()">
          <textarea #box rows="1" placeholder="Ask a question" aria-label="Question" [value]="draft()"
                    (input)="type(box)" (keydown.enter)="enter($any($event))"></textarea>
          <button class="send" type="submit" aria-label="Send" [disabled]="!canSend()">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
          </button>
        </form>
      </section>
    } @else {
      <button class="launcher" type="button" aria-label="Open the chat" [class.busy]="running()" (click)="open.set(true)">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12z" /><path d="M8.5 11h.01M12 11h.01M15.5 11h.01" /></svg>
        @if (attention()) {
          <span class="badge" aria-hidden="true"></span>
        }
      </button>
    }
  `,
  styles: `
    /* closed: a round button at the bottom right, outside the layout */
    :host { position: fixed; right: 20px; bottom: 20px; z-index: 1000; font: 14px/1.5 var(--font); }
    /* open: the shell's third grid column, full height, next to the page (app.css sets its width) */
    :host(.open) {
      position: sticky; top: 0; right: auto; bottom: auto; z-index: 5; height: 100vh; overflow: hidden;
      background: var(--surface); border-left: 1px solid var(--border);
    }
    .launcher {
      position: relative; display: grid; place-items: center; width: 56px; height: 56px;
      color: #fff; background: var(--primary); border: 0; border-radius: 50%; cursor: pointer;
      box-shadow: 0 6px 20px rgba(16, 24, 40, 0.25); transition: transform 0.2s ease, box-shadow 0.2s ease;
      animation: appear 0.2s ease both;
    }
    .launcher:hover { transform: translateY(-2px) scale(1.04); box-shadow: 0 10px 26px rgba(16, 24, 40, 0.3); }
    .badge {
      position: absolute; top: 3px; right: 3px; width: 13px; height: 13px; border-radius: 50%;
      background: var(--warn); border: 2px solid var(--surface); animation: pulse 1.4s ease-in-out infinite;
    }
    .panel { display: flex; flex-direction: column; width: calc(var(--chat-width, 400px) - 1px); height: 100%; animation: slide 0.28s ease both; }
    header { display: flex; align-items: center; gap: 10px; padding: 14px 12px 14px 16px; border-bottom: 1px solid var(--border); }
    .avatar { display: grid; place-items: center; flex: none; width: 32px; height: 32px; border-radius: 50%; background: var(--primary-soft); color: var(--primary); }
    .who { flex: 1; min-width: 0; display: flex; flex-direction: column; line-height: 1.25; }
    .sub { font-size: 12px; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .sub.live { color: var(--primary); }
    .icon {
      display: grid; place-items: center; flex: none; width: 32px; height: 32px; color: var(--text-muted);
      background: none; border: 0; border-radius: 8px; cursor: pointer;
    }
    .icon:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
    .icon:disabled { opacity: 0.4; cursor: default; }
    .log { flex: 1; min-height: 0; overflow-x: hidden; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; scrollbar-width: thin; scrollbar-gutter: stable; }
    .msg { display: flex; animation: rise 0.25s ease both; }
    .msg.human { justify-content: flex-end; }
    .bubble { max-width: 88%; padding: 9px 13px; border-radius: 14px; background: var(--surface-2); overflow-wrap: anywhere; }
    .msg.human .bubble { background: var(--primary); color: #fff; border-bottom-right-radius: 4px; white-space: pre-wrap; }
    .msg.ai .bubble { border-bottom-left-radius: 4px; }
    .answer ::ng-deep p { margin: 0 0 8px; }
    .answer ::ng-deep p:last-child { margin-bottom: 0; }
    .answer ::ng-deep ul, .answer ::ng-deep ol { margin: 0 0 8px; padding-left: 20px; }
    .answer ::ng-deep code { padding: 1px 5px; border-radius: 5px; background: var(--surface); font-size: 12px; }
    /* working: a sound wave and who is working on what (the line crossfades when it changes) */
    .working { display: flex; align-items: center; gap: 10px; font-size: 13px; }
    .say { display: inline-grid; min-width: 0; }
    .line { grid-area: 1 / 1; display: inline-flex; flex-wrap: wrap; align-items: baseline; gap: 6px; }
    .line strong { color: var(--primary); font-weight: 600; white-space: nowrap; }
    .swap-in { animation: swap-in 0.4s ease both; }
    .swap-out { animation: swap-out 0.3s ease both; }
    .wave { display: inline-flex; align-items: center; gap: 3px; height: 18px; }
    .wave i { width: 3px; height: 100%; border-radius: 3px; background: linear-gradient(180deg, var(--primary), #7c5cff); animation: wave 1.1s ease-in-out infinite; }
    .wave i:nth-child(2) { animation-delay: 0.12s; }
    .wave i:nth-child(3) { animation-delay: 0.24s; }
    .wave i:nth-child(4) { animation-delay: 0.36s; }
    .wave i:nth-child(5) { animation-delay: 0.48s; }
    .shimmer {
      font-weight: 500; color: transparent; background-clip: text; -webkit-background-clip: text; background-size: 300% 100%;
      background-image: linear-gradient(90deg, var(--text-muted) 0%, var(--text-muted) 40%, var(--text) 50%, var(--text-muted) 60%, var(--text-muted) 100%);
      animation: shimmer 2s linear infinite;
    }
    .fade-out { animation: fade-out 0.25s ease both; }
    /* the answer wipes in from the top */
    .reveal {
      -webkit-mask-image: linear-gradient(180deg, #000 50%, transparent 60%); mask-image: linear-gradient(180deg, #000 50%, transparent 60%);
      -webkit-mask-size: 100% 220%; mask-size: 100% 220%; animation: wipe 0.9s ease-out both;
    }
    /* the launcher while a run is going: a spinning ring */
    .launcher.busy::before {
      content: ''; position: absolute; inset: -4px; border-radius: 50%; animation: spin 1s linear infinite;
      background: conic-gradient(from 0deg, transparent 0 55%, var(--primary) 85%, #7c5cff);
      -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 3px));
      mask: radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 3px));
    }
    .hello { margin: auto 0; text-align: center; color: var(--text-muted); }
    .hello p { margin: 0 0 12px; }
    .chips { display: flex; flex-wrap: wrap; justify-content: center; gap: 6px; }
    .chip {
      font: inherit; font-size: 12px; padding: 4px 11px; color: var(--text); background: var(--surface-2);
      border: 1px solid var(--border); border-radius: 999px; cursor: pointer;
    }
    .chip:hover { border-color: var(--primary); color: var(--primary); }
    .error { padding: 8px 12px; border-radius: 10px; color: var(--danger); background: var(--danger-soft); font-size: 13px; }
    .composer { display: flex; align-items: flex-end; gap: 8px; margin: 0 14px 14px; padding: 6px 6px 6px 12px; border: 1px solid var(--border); border-radius: 14px; }
    .composer:focus-within { border-color: var(--primary); }
    textarea {
      flex: 1; min-width: 0; max-height: 140px; padding: 6px 0; resize: none; font: inherit; line-height: 22px;
      color: var(--text); background: transparent; border: 0; outline: 0;
    }
    .send {
      display: grid; place-items: center; flex: none; width: 34px; height: 34px; color: #fff;
      background: var(--primary); border: 0; border-radius: 10px; cursor: pointer;
    }
    .send:disabled { background: var(--border); cursor: default; }
    @keyframes slide { from { opacity: 0; transform: translateX(28px); } to { opacity: 1; transform: none; } }
    @keyframes appear { from { opacity: 0; transform: scale(0.8); } to { opacity: 1; transform: none; } }
    @keyframes rise { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
    @keyframes wave { 0%, 100% { transform: scaleY(0.3); opacity: 0.5; } 50% { transform: scaleY(1); opacity: 1; } }
    @keyframes shimmer { from { background-position: 100% 0; } to { background-position: 0% 0; } }
    @keyframes fade-out { to { opacity: 0; transform: translateY(-4px); } }
    @keyframes swap-in { from { opacity: 0; transform: translateY(7px); filter: blur(2px); } to { opacity: 1; transform: none; filter: none; } }
    @keyframes swap-out { to { opacity: 0; transform: translateY(-7px); filter: blur(2px); } }
    @keyframes wipe { from { -webkit-mask-position: 0 100%; mask-position: 0 100%; } to { -webkit-mask-position: 0 0; mask-position: 0 0; } }
    @keyframes spin { to { transform: rotate(360deg); } }
    @keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.18); } }
    /* phones: the open chat covers the screen */
    @media (max-width: 760px) {
      :host { right: 12px; bottom: 12px; }
      :host(.open) { position: fixed; inset: 0; z-index: 1000; height: auto; border-left: 0; }
      .panel { width: 100%; }
    }
    @media (prefers-reduced-motion: reduce) {
      .panel, .msg, .wave i, .shimmer, .swap-in, .swap-out, .badge, .launcher, .launcher.busy::before, .reveal, .fade-out {
        animation: none; transition: none;
      }
      .reveal { -webkit-mask-image: none; mask-image: none; }
    }
  `,
})
export class ChatWidget {
  protected readonly current = inject(CurrentRun);
  protected readonly session = this.current.session;
  /** Two-way: the shell gives the chat its column while it is open. */
  readonly open = model(false);
  protected readonly draft = signal('');
  protected readonly examples = EXAMPLES;
  protected readonly text = textOf;
  protected readonly html = markdownToHtml;
  private readonly log = viewChild<ElementRef<HTMLElement>>('log');
  private readonly box = viewChild<ElementRef<HTMLTextAreaElement>>('box');

  protected readonly running = computed(() => this.session().status() === 'running');
  protected readonly messages = computed(() => this.session().values().messages ?? []);
  protected readonly canSend = computed(() => !!this.draft().trim() && !this.running() && !this.session().interrupt());
  /** Something to look at while the chat is closed: a run in progress, or a question waiting for the user. */
  protected readonly attention = computed(() => this.running() || !!this.session().interrupt());
  /** ticks while a run is going, so a long step rotates its phrases */
  private readonly now = signal(Date.now());
  /** when the current agent started working (its phrases rotate from there) */
  private readonly since = signal({ key: '', at: 0 });

  /** Who is working right now: the running step's agent; else the supervisor finishing (every step done),
   * replanning (after a rejection) or planning. */
  private readonly workingOn = computed(() => {
    const values = this.session().values();
    const steps = values.plan?.steps ?? [];
    const status = (id: string) => values.step_status?.[id]?.status;
    const running = steps.find((s) => status(s.id) === 'running');
    if (running) return WORK[running.agent] ? running.agent : 'agent:' + running.agent;
    if (steps.length && steps.every((s) => status(s.id) === 'done')) return 'finishing';
    return values.replans ? 'replan' : 'planning';
  });

  /** The working line: who (bold) and what, the phrase rotating every few seconds while one agent works. */
  protected readonly work = computed(() => {
    const on = this.workingOn();
    const since = this.since();
    const known = WORK[on] ?? { who: on.replace(/^agent:/, ''), say: ['Working on it…'] };
    // the clock ticks every 0.7 s, so right after a change it can be behind `since`: never below the first phrase
    const i = since.key === on ? Math.floor(Math.max(0, this.now() - since.at) / PHRASE_MS) % known.say.length : 0;
    return { key: `${on}:${i}`, who: known.who, text: known.say[i] };
  });

  protected readonly statusText = computed(() => {
    if (this.running()) return `${this.work().who} · ${this.work().text}`;
    if (this.session().interrupt()) return 'Waiting for you';
    return 'Plans the agents for each question';
  });

  constructor() {
    // a new agent at work, or a new run: its phrases start from the first
    effect(() => {
      const on = this.workingOn();
      this.running();
      untracked(() => this.since.set({ key: on, at: Date.now() }));
    });
    const ticking = setInterval(() => {
      if (this.running()) this.now.set(Date.now());
    }, 700);
    inject(DestroyRef).onDestroy(() => clearInterval(ticking));
    // keep the newest message in view (new messages, progress, the answer)
    effect(() => {
      this.messages();
      this.work();
      this.open();
      setTimeout(() => {
        const el = this.log()?.nativeElement;
        if (el) el.scrollTop = el.scrollHeight;
      });
    });
  }

  protected async send(text = this.draft()): Promise<void> {
    const request = text.trim();
    if (!request || this.running() || this.session().interrupt()) return;
    this.draft.set('');
    this.resize();
    await this.session().ask(request);
  }

  protected async decide(decision: unknown): Promise<void> {
    await this.session().resume(decision);
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

  private resize(): void {
    setTimeout(() => {
      const el = this.box()?.nativeElement;
      if (!el) return;
      el.style.height = 'auto';
      el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
    });
  }
}
