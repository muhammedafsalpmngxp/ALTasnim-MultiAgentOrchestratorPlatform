/*
 * @altasnim/shared: used by the shell, every platform MFE and every agent UI.
 * Shared at runtime as a singleton by Native Federation (tsconfig path mapping).
 */
export * from './lib/models';
export * from './lib/config';
export * from './lib/run-session';
export * from './lib/orchestrator.service';
export * from './lib/current-run';
export * from './lib/run-events';
export * from './lib/agent-widget';
export * from './lib/ui/status-badge';
export * from './lib/ui/json-view';
export * from './lib/flow/flow-icons';
export * from './lib/flow/flow-model';
export * from './lib/flow/flow-diagram';
export * from './lib/ui/step-result';
export * from './lib/ui/decision-panel';
export * from './lib/ui/agent-card-view';
export * from './lib/ui/markdown';
