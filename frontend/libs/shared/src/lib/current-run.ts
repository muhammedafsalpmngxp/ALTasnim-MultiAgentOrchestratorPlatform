import { Injectable, inject, signal } from '@angular/core';

import { OrchestratorService } from './orchestrator.service';
import { RunSession } from './run-session';

/**
 * The conversation the user is having with the supervisor: one per browser tab. The shell's chat window asks
 * in it and the Multi Agent Flow page draws it; both inject this singleton (@altasnim/shared is shared at
 * runtime), so the flow page always shows what the chat asked.
 */
@Injectable({ providedIn: 'root' })
export class CurrentRun {
  private readonly orchestrator = inject(OrchestratorService);
  readonly session = signal<RunSession>(this.orchestrator.newSession());
  /** The shell's chat sidebar is open (any page may open it, e.g. "Ask the Assistant"). */
  readonly chatOpen = signal(false);

  /** Open the chat and ask (e.g. an example question on a page). */
  async ask(question: string): Promise<void> {
    this.chatOpen.set(true);
    const session = this.session();
    if (session.status() === 'running' || session.interrupt()) return;
    await session.ask(question);
  }

  /** A new conversation (a new supervisor thread). The previous one stays in Runs. */
  newChat(): void {
    this.session.set(this.orchestrator.newSession());
  }
}
