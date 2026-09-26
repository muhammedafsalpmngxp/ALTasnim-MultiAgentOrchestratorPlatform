import { loadRemoteModule } from '@angular-architects/native-federation';
import { AgentWidget, AgentWidgetLoader, agentRemoteName } from '@altasnim/shared';

const cache = new Map<string, Promise<AgentWidget | null>>();

/** Loads './Widget' from an agent team's micro-frontend (e.g. communication -> communication-ui). */
export const loadAgentWidget: AgentWidgetLoader = (agent: string) => {
  if (!cache.has(agent)) {
    cache.set(
      agent,
      loadRemoteModule(agentRemoteName(agent), './Widget')
        .then((m) => (m.widget as AgentWidget) ?? null)
        .catch(() => null), // no widget for this agent -> generic view
    );
  }
  return cache.get(agent)!;
};
