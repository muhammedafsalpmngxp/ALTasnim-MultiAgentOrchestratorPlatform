import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { AgentCard } from '../models';

/** Renders an agent's card (what the supervisor plans from). */
@Component({
  selector: 'alt-agent-card',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="card stack">
      <div class="row between">
        <h2>{{ card().name }}</h2>
        <span class="muted">v{{ card().version }} · {{ card().owner }}</span>
      </div>
      <p>{{ card().description }}</p>
      <div><strong>Use when:</strong> <span class="muted">{{ card().when_to_use }}</span></div>
      <div><strong>Not for:</strong> <span class="muted">{{ card().when_not_to_use }}</span></div>
      <div><strong>Approval:</strong> <span class="muted">{{ card().approval_mode }}</span></div>
      @if (params().length) {
        <div>
          <strong>Params</strong>
          <ul>
            @for (p of params(); track p.name) {
              <li><code>{{ p.name }}</code> <span class="muted">{{ p.description }}</span></li>
            }
          </ul>
        </div>
      }
      <div>
        <strong>Examples</strong>
        <ul>
          @for (e of card().examples; track e) {
            <li class="muted">{{ e }}</li>
          }
        </ul>
      </div>
    </div>
  `,
  styles: `
    .between { justify-content: space-between; }
    ul { margin: 4px 0 0; padding-left: 18px; }
  `,
})
export class AgentCardView {
  readonly card = input.required<AgentCard>();
  protected readonly params = computed(() =>
    Object.entries(this.card().params_schema?.properties ?? {}).map(([name, p]) => ({
      name,
      description: p.description ?? p.type ?? '',
    })),
  );
}
