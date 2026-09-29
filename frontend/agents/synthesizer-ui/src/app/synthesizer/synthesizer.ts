import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, OnDestroy, OnInit, signal, untracked } from '@angular/core';

import { SynthesizerService } from './synthesizer.service';
import { AgentCard, Run } from './synthesizer.models';
import { InputView, toInputView } from './synthesizer.view';
import { displaySteps, firstUnsettled, isSettled, pipelineSteps } from './synthesizer.pipeline';
import { renderMarkdown, withoutCitations } from '../markdown';

/** Poll fast while a request is running, slower when idle. */
const POLL_BUSY_MS = 1000;
const POLL_IDLE_MS = 3000;
/** How long each pipeline step stays orange before it turns green. */
const PIPELINE_STEP_MS = 450;

type RunLabel = 'running' | 'success' | 'failed' | 'error';
type Filter = 'all' | 'success' | 'failed' | 'running';
type DetailTab = 'data' | 'prompt' | 'raw';

/** Keys that hold data, not the name of the agent that sent it. */
const NOT_SENDERS = ['task', 'inputs', 'params', 'text', 'data', 'chunks', 'context', 'results'];

/** What the agent does with every request (shown before the first request arrives). */
export const HOW_IT_WORKS = [
  { title: 'Receive', text: 'Any JSON or text, on any path' },
  { title: 'Question', text: 'Taken from "question", "query", …' },
  { title: 'Evidence', text: 'Everything else is the data' },
  { title: 'LLM', text: 'Writes a short, direct answer' },
  { title: 'Reply', text: 'Answer + source URLs' },
];

/**
 * The Synthesizer console: live pipeline, the requests the agent received, and the selected request in detail.
 * Exposed to the shell in federation.config.mjs ('./Routes').
 */
@Component({
  selector: 'app-synthesizer',
  imports: [DatePipe, DecimalPipe],
  templateUrl: './synthesizer.html',
  styleUrl: './synthesizer.scss',
})
export class Synthesizer implements OnInit, OnDestroy {
  private readonly api = inject(SynthesizerService);
  private pollTimer?: ReturnType<typeof setTimeout>;
  private clockTimer?: ReturnType<typeof setInterval>;
  private pipelineTimer?: ReturnType<typeof setInterval>;
  private toastTimer?: ReturnType<typeof setTimeout>;
  private destroyed = false;
  private loaded = false;
  private readonly htmlCache = new Map<string, string>();

  readonly howItWorks = HOW_IT_WORKS;

  readonly apiUrl = signal('');
  readonly online = signal<boolean | null>(null);
  readonly card = signal<AgentCard | null>(null);
  readonly runs = signal<Run[]>([]); // newest first, as the API returns them
  readonly now = signal(Date.now());
  readonly toast = signal<{ text: string; kind: 'ok' | 'error' } | null>(null);

  // ---- list: search, filter, selection ----

  readonly query = signal('');
  readonly filter = signal<Filter>('all');
  /** null = follow the newest request live */
  private readonly selectedId = signal<string | null>(null);
  readonly following = computed(() => this.selectedId() === null);
  readonly detailTab = signal<DetailTab>('data');

  /** Full copies of runs (with the prompt), and data items opened with "Show more". */
  private readonly fullRuns = signal<Record<string, Run>>({});
  private readonly expanded = signal<ReadonlySet<string>>(new Set());

  // ---- derived state ----

  readonly endpoint = computed(() => (this.apiUrl() ? `${this.apiUrl()}/synthesize` : ''));
  readonly exampleCommand = computed(
    () =>
      `curl.exe -X POST ${this.endpoint() || 'http://localhost:8204/synthesize'} -H "Content-Type: application/json" ` +
      `-d '{"question":"What is the price of iPhone 16 in Oman?","web_search":{"chunks":["Lulu Oman: iPhone 16 128GB OMR 319"]}}'`,
  );
  readonly modelLabel = computed(() => this.card()?.llm?.model ?? 'No LLM configured');

  readonly counts = computed(() => {
    const labels = this.runs().map((r) => this.runLabel(r));
    return {
      all: labels.length,
      success: labels.filter((l) => l === 'success').length,
      failed: labels.filter((l) => l === 'failed' || l === 'error').length,
      running: labels.filter((l) => l === 'running').length,
    };
  });

  readonly kpis = computed(() => {
    const c = this.counts();
    const finished = c.success + c.failed;
    const times = this.runs()
      .filter((r) => r.state === 'done' && r.seconds != null)
      .map((r) => r.seconds as number);
    return {
      successRate: finished ? Math.round((c.success / finished) * 100) : null,
      avgSeconds: times.length ? times.reduce((a, b) => a + b, 0) / times.length : null,
      maxSeconds: times.length ? Math.max(...times) : null,
    };
  });

  readonly visibleRuns = computed(() => {
    const q = this.query().trim().toLowerCase();
    const filter = this.filter();
    return this.runs().filter((run) => {
      const label = this.runLabel(run);
      if (filter === 'success' && label !== 'success') return false;
      if (filter === 'failed' && label !== 'failed' && label !== 'error') return false;
      if (filter === 'running' && label !== 'running') return false;
      if (!q) return true;
      return [run.question ?? '', this.sender(run), this.answerText(run), run.endpoint ?? '']
        .some((text) => text.toLowerCase().includes(q));
    });
  });

  readonly selected = computed<Run | null>(() => {
    const runs = this.runs();
    const id = this.selectedId();
    return (id && runs.find((r) => r.id === id)) || runs[0] || null;
  });

  // ---- live pipeline (the selected request; the newest one when following live) ----

  readonly pipelineRun = this.selected;
  /** Steps before the cursor are shown as they are; the one at the cursor is orange. */
  private readonly pipelineCursor = signal(0);
  private pipelineRunId: string | null | undefined;

  private readonly pipelineActual = computed(() => {
    const run = this.pipelineRun();
    return pipelineSteps(run, run ? this.dataParts(run).length : 0, run ? this.elapsed(run) : 0);
  });

  readonly pipeline = computed(() => displaySteps(this.pipelineActual(), this.pipelineCursor()));

  readonly pipelineStatus = computed(() => {
    const steps = this.pipeline();
    if (!this.pipelineRun()) return { state: 'pipe-idle', label: 'Waiting' };
    if (steps.some((s) => s.state === 'error')) return { state: 'pipe-failed', label: 'Failed' };
    if (steps.every((s) => s.state === 'done' || s.state === 'skipped')) return { state: 'pipe-complete', label: 'Complete' };
    return { state: 'pipe-running', label: 'Running' };
  });

  constructor() {
    // the prompt lives only in GET /runs/{id}: load it for the selected request
    effect(() => {
      const run = this.selected();
      if (run) untracked(() => void this.loadFull(run));
    });
  }

  /** Show the selected request's steps: played from the start for a new live request, else as they are. */
  private syncPipeline(animate: boolean): void {
    const id = this.pipelineRun()?.id ?? null;
    if (id === this.pipelineRunId) return;
    this.pipelineRunId = id;
    this.pipelineCursor.set(animate ? 0 : firstUnsettled(this.pipelineActual()));
  }

  replayPipeline(): void {
    this.pipelineCursor.set(0);
  }

  private stepPipeline(): void {
    const steps = this.pipelineActual();
    const cursor = this.pipelineCursor();
    if (cursor < steps.length && isSettled(steps[cursor].state)) this.pipelineCursor.set(cursor + 1);
  }

  // ---- lifecycle ----

  async ngOnInit(): Promise<void> {
    this.apiUrl.set(await this.api.apiUrl());
    this.clockTimer = setInterval(() => this.now.set(Date.now()), 1000);
    this.pipelineTimer = setInterval(() => this.stepPipeline(), PIPELINE_STEP_MS);
    await this.poll();
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    clearTimeout(this.pollTimer);
    clearInterval(this.clockTimer);
    clearInterval(this.pipelineTimer);
    clearTimeout(this.toastTimer);
  }

  private async poll(): Promise<void> {
    await this.refresh();
    if (this.destroyed) return;
    this.pollTimer = setTimeout(() => this.poll(), this.counts().running ? POLL_BUSY_MS : POLL_IDLE_MS);
  }

  async refresh(): Promise<void> {
    try {
      const previousNewest = this.runs()[0]?.id;
      const runs = await this.api.runs();
      this.runs.set(runs);
      if (this.online() !== true) {
        this.online.set(true);
        this.card.set(await this.api.card());
      }
      if (this.selectedId() && !runs.some((r) => r.id === this.selectedId())) this.selectedId.set(null);
      const newArrived = this.loaded && runs[0]?.id !== previousNewest;
      this.syncPipeline(newArrived && this.following());
      this.loaded = true;
      const selected = this.selected();
      if (selected) void this.loadFull(selected); // keep the prompt up to date when it finishes
    } catch {
      this.online.set(false);
    }
  }

  // ---- selection ----

  isSelected(run: Run): boolean {
    return this.selected()?.id === run.id;
  }

  select(run: Run): void {
    this.selectedId.set(run.id === this.runs()[0]?.id ? null : run.id); // the newest one = follow live
    this.syncPipeline(false);
  }

  followLive(): void {
    this.selectedId.set(null);
    this.syncPipeline(false);
  }

  /** Arrow keys move through the list. */
  onListKey(event: KeyboardEvent): void {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    const list = this.visibleRuns();
    const index = list.findIndex((r) => this.isSelected(r));
    const next = list[Math.min(list.length - 1, Math.max(0, index + (event.key === 'ArrowDown' ? 1 : -1)))];
    if (!next) return;
    event.preventDefault();
    this.select(next);
    setTimeout(() => document.getElementById(`run-${next.id}`)?.focus());
  }

  private async loadFull(run: Run): Promise<void> {
    const known = this.fullRuns()[run.id];
    if (known && known.state === run.state) return;
    try {
      const full = await this.api.run(run.id);
      if (full) this.fullRuns.update((all) => ({ ...all, [run.id]: full }));
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

  rawOf(run: Run): string {
    return JSON.stringify(run.inputs ?? {}, null, 2);
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

  async copyText(text: string, what: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      this.showToast(`${what} copied`, 'ok');
    } catch {
      this.showToast('Could not copy: the browser blocked clipboard access.', 'error');
    }
  }

  async clear(): Promise<void> {
    if (!confirm('Clear all requests from the agent’s history?')) return;
    try {
      await this.api.clearRuns();
    } catch {
      this.showToast('Could not clear the history: the agent is not reachable.', 'error');
      return;
    }
    this.selectedId.set(null);
    this.fullRuns.set({});
    this.htmlCache.clear();
    await this.refresh();
  }

  private showToast(text: string, kind: 'ok' | 'error'): void {
    clearTimeout(this.toastTimer);
    this.toast.set({ text, kind });
    this.toastTimer = setTimeout(() => this.toast.set(null), kind === 'ok' ? 1800 : 5000);
  }

  // ---- display helpers ----

  runLabel(run: Run): RunLabel {
    if (run.state === 'running') return 'running';
    if (run.state === 'error') return 'error';
    return run.result?.status === 'ok' ? 'success' : 'failed';
  }

  statusText(run: Run): string {
    return { running: 'Running', success: 'Answered', failed: 'No data', error: 'Error' }[this.runLabel(run)];
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

  answerText(run: Run): string {
    return withoutCitations(run.result?.answer ?? run.result?.summary ?? '');
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

  sourcesOf(run: Run): { url: string; site: string }[] {
    return (run.result?.sources ?? []).map((url) => {
      try {
        return { url, site: new URL(url).hostname.replace(/^www\./, '') };
      } catch {
        return { url, site: url };
      }
    });
  }

  elapsed(run: Run): number {
    return Math.max(0, Math.floor((this.now() - new Date(run.received_at).getTime()) / 1000));
  }

  /** "12s ago", "5m ago", "2h ago" */
  ago(run: Run): string {
    const s = this.elapsed(run);
    if (s < 60) return s < 5 ? 'just now' : `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
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
