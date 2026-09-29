import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { OrchestratorService } from '@altasnim/shared';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  private readonly orchestrator = inject(OrchestratorService);
  protected readonly pending = signal(0);
  protected readonly backendUp = signal(true);

  protected readonly platformLinks = [
    { path: '/flow', label: 'Multi Agent Flow' },
    { path: '/runs', label: 'Runs' },
    { path: '/approvals', label: 'Approvals' },
    { path: '/admin', label: 'Agents & policies' },
  ];
  protected readonly agentLinks = [
    { path: '/agents/web-search', label: 'Web search' },
    { path: '/agents/communication', label: 'Communication' },
    { path: '/agents/verifier', label: 'Verifier' },
    { path: '/agents/rag', label: 'RAG' },
  ];

  constructor() {
    const poll = () =>
      this.orchestrator
        .pendingApprovals()
        .then((items) => {
          this.pending.set(items.length);
          this.backendUp.set(true);
        })
        .catch(() => this.backendUp.set(false));
    poll();
    const timer = setInterval(poll, 10_000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }
}
