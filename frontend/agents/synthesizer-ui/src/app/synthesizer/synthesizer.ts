import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, computed, ElementRef, inject, OnDestroy, OnInit, signal, viewChild } from '@angular/core';

import { SynthesizerService } from './synthesizer.service';
import { AgentCard, Run } from './synthesizer.models';
import { InputView, toInputView } from './synthesizer.view';
import { renderMarkdown } from '../markdown';

const POLL_MS = 3000;

/** What happens behind every request, shown in the welcome message. */
export const FLOW_STEPS = ['Receive any data', 'Find the question', 'Select the evidence', 'Ask the LLM', 'Reply'];

type RunLabel = 'running' | 'success' | 'failed' | 'error';

/** Keys that hold data, not the name of the agent that sent it. */
const NOT_SENDERS = ['task', 'inputs', 'params', 'text', 'data', 'chunks', 'context', 'results'];

/**
 * The Synthesizer screen as a chat: each request is a question (from the agent that sent it) and the answer.
 * Exposed to the shell in federation.config.mjs ('./Routes' and './Component').
 */
@Component({
  selector: 'app-synthesizer',
  imports: [DatePipe, DecimalPipe],
  templateUrl: './synthesizer.html',
  styleUrl: './synthesizer.scss',
})
export class Synthesizer implements OnInit, OnDestroy {
  private readonly api = inject(SynthesizerService);
  private readonly threadEl = viewChild<ElementRef<HTMLElement>>('thread');
  private pollTimer?: ReturnType<typeof setInterval>;
  private clockTimer?: ReturnType<typeof setInterval>;
  private lastCount = -1;
  private readonly htmlCache = new Map<string, string>();

  readonly flowSteps = FLOW_STEPS;

  readonly apiUrl = signal('');
  readonly online = signal<boolean | null>(null);
  readonly card = signal<AgentCard | null>(null);
  readonly runs = signal<Run[]>([]); // newest first, as the API returns them
  readonly notice = signal('');
  readonly copiedId = signal<string | null>(null);
  readonly now = signal(Date.now());

  /** Answers whose details are open, and their full copies (with the prompt). */
  private readonly openDetails = signal<ReadonlySet<string>>(new Set());
  private readonly fullRuns = signal<Record<string, Run>>({});
  /** Data items opened with "Show more", keyed "<run>:<input>:<index>" */
  private readonly expanded = signal<ReadonlySet<string>>(new Set());

  // ---- derived state ----

  /** Oldest first, like a chat. */
  readonly conversation = computed(() => [...this.runs()].reverse());

  readonly stats = computed(() => {
    const runs = this.runs();
    const labels = runs.map((r) => this.runLabel(r));
    const timed = runs.filter((r) => r.state === 'done' && r.seconds != null).map((r) => r.seconds as number);
    return {
      total: runs.length,
      answered: labels.filter((l) => l === 'success').length,
      failed: labels.filter((l) => l === 'failed' || l === 'error').length,
      avgSeconds: timed.length ? timed.reduce((a, b) => a + b, 0) / timed.length : null,
    };
  });

  readonly modelLabel = computed(() => this.card()?.llm?.model ?? 'No LLM configured');

  // ---- lifecycle ----

  async ngOnInit(): Promise<void> {
    this.apiUrl.set(await this.api.apiUrl());
    await this.refresh();
    this.pollTimer = setInterval(() => this.refresh(), POLL_MS);
    this.clockTimer = setInterval(() => this.now.set(Date.now()), 1000);
  }

  ngOnDestroy(): void {
    clearInterval(this.pollTimer);
    clearInterval(this.clockTimer);
  }

  async refresh(): Promise<void> {
    try {
      const runs = await this.api.runs();
      this.runs.set(runs);
      if (this.online() !== true) {
        this.online.set(true);
        this.card.set(await this.api.card());
      }
      if (runs.length !== this.lastCount) {
        const first = this.lastCount === -1;
        this.lastCount = runs.length;
        this.scrollToEnd(first ? 'auto' : 'smooth'); // a new message arrived
      }
      for (const id of this.openDetails()) void this.loadFull(id); // keep open details up to date
    } catch {
      this.online.set(false);
    }
  }

  private scrollToEnd(behavior: ScrollBehavior): void {
    setTimeout(() => this.threadEl()?.nativeElement.lastElementChild?.scrollIntoView({ behavior, block: 'end' }), 50);
  }

  // ---- details under an answer ----

  isOpen(run: Run): boolean {
    return this.openDetails().has(run.id);
  }

  toggleDetails(run: Run): void {
    const next = new Set(this.openDetails());
    if (next.has(run.id)) next.delete(run.id);
    else {
      next.add(run.id);
      void this.loadFull(run.id);
    }
    this.openDetails.set(next);
  }

  private async loadFull(id: string): Promise<void> {
    const known = this.fullRuns()[id];
    const current = this.runs().find((r) => r.id === id);
    if (known && current && known.state === current.state) return;
    try {
      const full = await this.api.run(id);
      if (full) this.fullRuns.update((all) => ({ ...all, [id]: full }));
    } catch {
      /* keep what we have */
    }
  }

  /** undefined = still loading, null = no prompt was sent */
  promptOf(run: Run): string | null | undefined {
    const full = this.fullRuns()[run.id];
    return full && full.state === run.state ? (full.prompt ?? null) : undefined;
  }

  inputsOf(run: Run): InputView[] {
    return this.dataParts(run).map(([name, value]) => toInputView(name, value));
  }

  /**
   * The parts of a request's data, with a nested "inputs" object opened up:
   * {"task": {...}, "inputs": {"web_search": {...}}} -> web_search, task
   */
  private dataParts(run: Run): [string, unknown][] {
    const data = run.inputs ?? {};
    const nested = data['inputs'];
    const isObject = nested !== null && typeof nested === 'object' && !Array.isArray(nested);
    const inner = isObject ? Object.entries(nested as Record<string, unknown>) : [];
    return [...inner, ...Object.entries(data).filter(([key]) => !(isObject && key === 'inputs'))];
  }

  // ---- actions ----

  async copy(run: Run): Promise<void> {
    try {
      await navigator.clipboard.writeText(this.answerText(run));
      this.copiedId.set(run.id);
      setTimeout(() => this.copiedId.set(null), 1500);
    } catch {
      this.notice.set('Could not copy: the browser blocked clipboard access.');
    }
  }

  async clear(): Promise<void> {
    await this.api.clearRuns();
    this.openDetails.set(new Set());
    this.fullRuns.set({});
    this.htmlCache.clear();
    this.refresh();
  }

  // ---- display helpers ----

  runLabel(run: Run): RunLabel {
    if (run.state === 'running') return 'running';
    if (run.state === 'error') return 'error';
    return run.result?.status === 'ok' ? 'success' : 'failed';
  }

  /** Who asked: the agent whose data came in, e.g. "web_search". */
  sender(run: Run): string {
    const name = this.dataParts(run).map(([key]) => key).find((key) => !NOT_SENDERS.includes(key));
    return name ?? 'Agent';
  }

  initials(name: string): string {
    const parts = name.split(/[_\s-]+/).filter(Boolean);
    return (parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)).toUpperCase();
  }

  /** The answer without [1]-style reference marks (older answers may still contain them). */
  answerText(run: Run): string {
    return (run.result?.answer ?? run.result?.summary ?? '').replace(/\s*\[\d+(?:\s*[,-]\s*\d+)*\]/g, '');
  }

  answerHtml(run: Run): string {
    const key = `${run.id}:${run.state}`;
    let html = this.htmlCache.get(key);
    if (html === undefined) {
      html = renderMarkdown(this.answerText(run));
      this.htmlCache.set(key, html);
    }
    return html;
  }

  elapsed(run: Run): number {
    return Math.max(0, Math.floor((this.now() - new Date(run.received_at).getTime()) / 1000));
  }

  private itemKey(run: Run, input: string, index: number): string {
    return `${run.id}:${input}:${index}`;
  }

  isExpanded(run: Run, input: string, index: number): boolean {
    return this.expanded().has(this.itemKey(run, input, index));
  }

  toggleItem(run: Run, input: string, index: number): void {
    const key = this.itemKey(run, input, index);
    const next = new Set(this.expanded());
    if (next.has(key)) next.delete(key);
    else next.add(key);
    this.expanded.set(next);
  }

  isLong(text: string): boolean {
    return text.length > 260;
  }
}
