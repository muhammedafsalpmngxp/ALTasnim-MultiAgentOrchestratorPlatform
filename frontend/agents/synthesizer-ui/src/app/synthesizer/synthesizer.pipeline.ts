/**
 * The live pipeline: what the agent does with one request, step by step (agent.py / api.py).
 * Orange = the step is running, green = done, red = it failed there.
 */

import { Run } from './synthesizer.models';

export type StepState = 'pending' | 'active' | 'done' | 'error' | 'skipped';

export interface PipelineStep {
  label: string;
  state: StepState;
  detail: string;
}

export const PIPELINE_LABELS = ['Received', 'Question', 'Evidence', 'LLM', 'Reply'];

/** A step that will not change any more. */
export function isSettled(state: StepState): boolean {
  return state === 'done' || state === 'error' || state === 'skipped';
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`;
}

/**
 * The real state of each step, from GET /runs. The API only knows running / done / error. Steps 1-3 happen
 * before the run is recorded, so they are done as soon as the run shows up.
 */
export function pipelineSteps(run: Run | null, dataParts: number, elapsed: number): PipelineStep[] {
  const [received, question, evidence, llm, reply] = PIPELINE_LABELS;
  if (!run) return PIPELINE_LABELS.map((label) => ({ label, state: 'pending', detail: '' }));

  const model = run.llm?.model ?? null;
  const noData = run.state === 'done' && run.result?.status !== 'ok'; // answer() stops before the LLM
  const sources = run.result?.sources?.length ?? 0;

  let llmStep: PipelineStep;
  if (run.state === 'running') llmStep = { label: llm, state: 'active', detail: `${model ?? 'Summaries'} · ${elapsed}s` };
  else if (run.state === 'error') llmStep = { label: llm, state: 'error', detail: 'Call failed' };
  else if (noData) llmStep = { label: llm, state: 'pending', detail: '' };
  else if (model) llmStep = { label: llm, state: 'done', detail: model };
  else llmStep = { label: llm, state: 'skipped', detail: 'Not configured' };

  return [
    { label: received, state: 'done', detail: run.endpoint ?? 'POST /synthesize' },
    { label: question, state: 'done', detail: run.question ? 'Found in the request' : 'Worked out from the data' },
    noData
      ? { label: evidence, state: 'error', detail: 'No data sent' }
      : { label: evidence, state: 'done', detail: plural(dataParts, 'part') },
    llmStep,
    run.state === 'done' && !noData
      ? { label: reply, state: 'done', detail: `${run.seconds ?? 0}s · ${plural(sources, 'source')}` }
      : { label: reply, state: 'pending', detail: '' },
  ];
}

/** Index of the first step that is not finished yet (steps.length when all are). */
export function firstUnsettled(steps: PipelineStep[]): number {
  const i = steps.findIndex((s) => !isSettled(s.state));
  return i === -1 ? steps.length : i;
}

/**
 * What is on screen: steps before `cursor` as they are, the step at `cursor` orange (once it has started),
 * the rest waiting. Moving the cursor one step at a time makes every step go orange, then green.
 */
export function displaySteps(steps: PipelineStep[], cursor: number): PipelineStep[] {
  return steps.map((step, i) => {
    if (i < cursor) return step;
    if (i === cursor && step.state !== 'pending') return { ...step, state: 'active' };
    return { ...step, state: 'pending', detail: '' };
  });
}
