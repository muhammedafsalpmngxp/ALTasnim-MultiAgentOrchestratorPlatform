import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

/** Shown when a micro-frontend cannot be loaded: only that section fails, never the whole shell. */
@Component({
  selector: 'alt-remote-unavailable',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <div class="card">
        <h2>{{ remote }} is not available</h2>
        <p class="muted">
          The micro-frontend <code>{{ remote }}</code> could not be loaded. Start it with
          <code>npm run start:{{ remote }}</code> (or <code>npm start</code> for all apps).
        </p>
      </div>
    </div>
  `,
})
export class RemoteUnavailable {
  protected readonly remote = inject(ActivatedRoute).snapshot.data['remote'] as string;
}
