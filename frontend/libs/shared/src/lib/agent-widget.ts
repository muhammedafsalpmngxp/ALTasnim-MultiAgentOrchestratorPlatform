import { InjectionToken, Type } from '@angular/core';

/**
 * Contract every agent UI (frontend/agents/<name>-ui) exposes as './Widget'.
 *
 * resultView    inputs: { result: AgentOutput }
 * approvalForm  inputs: { request: <agent interrupt payload>, decide: (decision) => void }
 *
 * Both are optional. Without them the platform falls back to a generic view.
 */
export interface AgentWidget {
  agent: string;
  resultView?: Type<unknown>;
  approvalForm?: Type<unknown>;
}

export type AgentWidgetLoader = (agent: string) => Promise<AgentWidget | null>;

/**
 * Provided by the shell (which owns the federation manifest). Remotes inject it
 * optionally: when a remote runs standalone, there is no loader and the generic
 * fallback views are used.
 */
export const AGENT_WIDGET_LOADER = new InjectionToken<AgentWidgetLoader>('AGENT_WIDGET_LOADER');

/** web_search -> web-search-ui (the remote name in federation.manifest.json) */
export function agentRemoteName(agent: string): string {
  return `${agent.replace(/_/g, '-')}-ui`;
}
