import { AgentWidget } from '@altasnim/shared';

import { AnswerView } from './answer-view';

/** Exposed as './Widget'. */
export const widget: AgentWidget = {
  agent: 'synthesizer',
  resultView: AnswerView,
};
