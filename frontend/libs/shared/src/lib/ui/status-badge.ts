import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

type Tone = 'neutral' | 'info' | 'ok' | 'warn' | 'danger';

const TONES: Record<string, Tone> = {
  done: 'ok', ok: 'ok', idle: 'ok', passed: 'ok', sent: 'ok',
  running: 'info', busy: 'info', queued: 'neutral',
  waiting_approval: 'warn', interrupted: 'warn', pending: 'warn', revise: 'warn',
  failed: 'danger', error: 'danger', rejected: 'danger',
};

@Component({
  selector: 'alt-status-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="badge" [attr.data-tone]="tone()">{{ label() }}</span>`,
  styles: `
    .badge { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 600;
             background: var(--surface-2); color: var(--text-muted); white-space: nowrap; }
    .badge[data-tone='info'] { background: var(--info-soft); color: var(--info); }
    .badge[data-tone='ok'] { background: var(--ok-soft); color: var(--ok); }
    .badge[data-tone='warn'] { background: var(--warn-soft); color: var(--warn); }
    .badge[data-tone='danger'] { background: var(--danger-soft); color: var(--danger); }
  `,
})
export class StatusBadge {
  readonly status = input.required<string>();
  protected readonly tone = computed<Tone>(() => TONES[this.status()] ?? 'neutral');
  protected readonly label = computed(() => (this.status() === 'idle' ? 'done' : this.status().replace(/_/g, ' ')));
}
