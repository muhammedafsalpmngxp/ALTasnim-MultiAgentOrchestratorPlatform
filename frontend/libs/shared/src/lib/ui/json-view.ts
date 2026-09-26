import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

@Component({
  selector: 'alt-json-view',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <details [open]="open()">
      <summary class="muted">{{ label() }}</summary>
      <pre>{{ text() }}</pre>
    </details>
  `,
  styles: `
    summary { cursor: pointer; font-size: 12px; }
    pre { margin: 6px 0 0; padding: 10px; background: var(--surface-2); border-radius: var(--radius-sm);
          overflow: auto; max-height: 320px; white-space: pre-wrap; word-break: break-word; }
  `,
})
export class JsonView {
  readonly value = input<unknown>();
  readonly label = input('JSON');
  readonly open = input(false);
  protected readonly text = computed(() => JSON.stringify(this.value(), null, 2));
}
