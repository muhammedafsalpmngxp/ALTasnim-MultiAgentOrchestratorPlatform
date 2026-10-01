import { AgentWidget } from '@altasnim/shared';

import { PassagesView } from './passages-view';

/** Exposed as './Widget'. The platform renders `resultView` for every rag step (Runs, Multi Agent Flow). */
export const widget: AgentWidget = {
  agent: 'rag',
  resultView: PassagesView,
};
