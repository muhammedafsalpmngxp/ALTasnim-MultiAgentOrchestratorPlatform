import { InjectionToken } from '@angular/core';

/**
 * Base URL of the orchestrator deployment (LangGraph Agent Server :8100).
 * Dev: proxied by proxy.conf.json. Prod: the API gateway serves the same path.
 */
export const ORCHESTRATOR_API = new InjectionToken<string>('ORCHESTRATOR_API', {
  providedIn: 'root',
  factory: () => `${location.origin}/api/orchestrator`,
});

export const ORCHESTRATOR_ASSISTANT = 'orchestrator';

/** Base URL of one agent deployment's custom routes (card, /custom/*), e.g. web_search -> /api/agents/web-search */
export function agentApiUrl(agent: string): string {
  return `${location.origin}/api/agents/${agent.replace(/_/g, '-')}`;
}
