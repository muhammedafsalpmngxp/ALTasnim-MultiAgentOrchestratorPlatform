import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

import { Icon } from './icon';

/** Shown when a micro-frontend cannot be loaded: only that section fails, never the whole shell. */
@Component({
  selector: 'alt-remote-unavailable',
  imports: [Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <div class="card empty">
        <span class="badge-icon"><alt-icon name="offline" [size]="26" /></span>
        <h2>This section is offline</h2>
        <p class="muted">
          The micro-frontend <code>{{ remote }}</code> could not be loaded. The rest of the platform keeps working.
        </p>
        <div class="how">
          <span class="muted">Start it with</span>
          <code>npm run start:{{ remote }}</code>
          <span class="muted">or all apps with</span>
          <code>npm start</code>
        </div>
        <button class="btn btn-primary" type="button" (click)="reload()">Try again</button>
      </div>
    </div>
  `,
  styles: `
    .empty { display: flex; flex-direction: column; align-items: center; gap: 10px; max-width: 560px; margin: 48px auto; padding: 40px 32px; text-align: center; }
    .empty h2 { margin: 6px 0 0; font-size: 18px; }
    .empty p { margin: 0; }
    .badge-icon { display: grid; place-items: center; width: 56px; height: 56px; border-radius: 16px; color: var(--warn); background: var(--warn-soft); }
    .how { display: flex; flex-wrap: wrap; justify-content: center; align-items: center; gap: 6px; margin: 6px 0 10px; font-size: 13px; }
  `,
})
export class RemoteUnavailable {
  protected readonly remote = inject(ActivatedRoute).snapshot.data['remote'] as string;

  protected reload(): void {
    location.reload();
  }
}
