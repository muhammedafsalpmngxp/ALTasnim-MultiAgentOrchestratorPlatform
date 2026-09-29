/**
 * Mirrors backend/web_search_agent: card.WebSearchResult (the step `result` the verifier gets) and the full run
 * details streamed by finalize.py. Keep both in sync.
 */

export type Freshness = 'day' | 'week' | 'month' | 'year';
export type ExtractionMethod = 'trafilatura' | 'playwright+trafilatura' | 'snippet';

/** Body of POST /custom/search/stream (the agent page's own test console). */
export interface WebSearchRequest {
  query: string;
  trace_id?: string;
  top_k?: number;
  freshness?: Freshness | null;
  include_domains?: string[];
  exclude_domains?: string[];
}

export interface LLMInfo {
  planner_model: string | null;
}

export interface Evidence {
  rank: number;
  citation_id: number;
  title: string;
  url: string;
  domain: string;
  published_date: string | null;
  content: string;
  relevance_score: number;
  final_score: number;
  extraction_method: ExtractionMethod;
}

export interface Source {
  citation_id: number;
  title: string;
  url: string;
  domain: string;
  published_date: string | null;
  author: string | null;
}

export type StepId = 'plan' | 'search' | 'extract' | 'chunk' | 'rerank' | 'verify';
export type StepStatus = 'pending' | 'running' | 'done' | 'skipped' | 'failed';

export interface PipelineStep {
  id: StepId;
  title: string;
  status: StepStatus;
  /** Seconds; null while pending/running or when skipped. */
  duration_s: number | null;
  detail: string;
  items: string[];
}

/** All values in seconds. */
export interface Timings {
  plan_s: number;
  search_s: number;
  extract_s: number;
  chunk_s: number;
  rerank_s: number;
  total_s: number;
}

/** One of the top contents in the step result. */
export interface TopContent {
  rank: number;
  title: string;
  url: string;
  content: string;
}

/**
 * The web_search step's `result` (card.WebSearchResult): what the orchestrator passes to the verifier.
 * Only the input question and the top 3 contents, plus the platform's required status / summary.
 */
export interface StepResult {
  status: 'ok' | 'failed';
  summary: string;
  question: string;
  findings: TopContent[];
  /** URLs of the top contents, same order; checked by the verifier. */
  sources: string[];
}

/** What happened when the output was sent to one target (WEB_SEARCH_SEND_TO: verifier / synthesizer). */
export interface Handoff {
  status: 'sent' | 'failed' | 'not_configured';
  url: string | null;
  /** e.g. /verify, /synthesize */
  path?: string;
  host?: string;
  passed?: boolean | null;
  issues?: string[];
  warnings?: string[];
  summary?: string;
  /** What the route answered (a verifier's verdict fields are also copied above). */
  response?: unknown;
  error?: string;
}

/** Everything one run produced: the console's stream `result` event and /custom/sources. */
export interface RunDetails extends StepResult {
  citations: Source[];
  evidence: Evidence[];
  context: string;
  query: string;
  search_queries: string[];
  provider_used: string | null;
  reranker: string;
  llm: LLMInfo;
  steps: PipelineStep[];
  timings: Timings;
  warnings: string[];
  trace_id: string;
  source_agent: string;
  created_at: string;
  /** One entry per URL the output was sent to (WEB_SEARCH_VERIFIER_PATH routes found on the network). */
  handoffs?: Record<string, Handoff>;
  /** The first verdict among the handoffs (older runs only have this). */
  verification?: Handoff;
  /** "Retry" count / time: the output sent to the output agents again (no search, no LLM). */
  retries?: number;
  retried_at?: string;
}

/** GET /custom/history rows. */
export interface HistoryEntry {
  trace_id: string;
  query: string;
  status: string;
  created_at: string;
  source_agent: string | null;
  sources: number;
  total_s: number | null;
  /** Start of the top content. */
  preview: string;
}

/** Events from POST /custom/search/stream (LangGraph custom stream events relayed as SSE). */
export type SearchStreamEvent =
  | { type: 'steps'; steps: PipelineStep[] }
  | { type: 'step'; step: PipelineStep }
  | { type: 'result'; result: RunDetails }
  | { type: 'error'; error: string };

/** A step result as it arrives from the platform (`AgentOutput`); a failed/stubbed step may have only status + summary. */
export function toStepResult(output: Record<string, unknown> | null | undefined): StepResult | null {
  if (!output) {
    return null;
  }
  const r = output as Partial<StepResult>;
  return {
    status: r.status === 'ok' ? 'ok' : 'failed',
    summary: r.summary ?? '',
    question: r.question ?? '',
    findings: r.findings ?? [],
    sources: r.sources ?? [],
  };
}

/** Name of the DOM event dispatched on `window` after every console search, for other micro-frontends. */
export const WEB_SEARCH_RESULT_EVENT = 'web-search-ui:result';
