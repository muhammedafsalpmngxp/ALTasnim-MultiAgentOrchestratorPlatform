import { AgentWidget } from '@altasnim/shared';

import { VerdictView } from './verdict-view';

/** Exposed as './Widget'. */
export const widget: AgentWidget = {
  agent: 'verifier',
  resultView: VerdictView,
};
