import { AgentWidget } from '@altasnim/shared';

import { SearchResultView } from './search-result-view';

/** Exposed as './Widget'. The platform renders `resultView` for every web_search step. */
export const widget: AgentWidget = {
  agent: 'web_search',
  resultView: SearchResultView,
};
