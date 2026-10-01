import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { AgentAdmin, OrchestratorService, PlanningText } from '@altasnim/shared';

type Key = keyof PlanningText;
type Draft = Record<Key, string>; // examples: one per line

/** Same limits as the supervisor (registry/overrides.py PlanningText). */
const FIELDS: { key: Key; label: string; hint: string; max: number; rows: number }[] = [
  { key: 'description', label: 'Description', hint: 'What the agent does, in one or two sentences.', max: 600, rows: 2 },
  { key: 'when_to_use', label: 'When to use', hint: 'The questions it should get.', max: 1500, rows: 3 },
  { key: 'when_not_to_use', label: 'When not to use', hint: 'The questions another agent answers better.', max: 1500, rows: 3 },
  { key: 'examples', label: 'Examples', hint: 'Questions it answers, one per line (up to 12).', max: 300, rows: 4 },
];
const MAX_EXAMPLES = 12;

const lines = (text: string) => text.split('\n').map((l) => l.trim()).filter(Boolean);
const asText = (v: string | string[] | undefined) => (Array.isArray(v) ? v.join('\n') : (v ?? ''));
const same = (key: Key, a: string, b: string) => (key === 'examples' ? lines(a).join('\n') === lines(b).join('\n') : a.trim() === b.trim());

/**
 * What the supervisor reads when it chooses agents, customised per agent: saved on the supervisor's machine
 * (data/agent_overrides.yaml) and used from the next question. A field equal to the agent's own card is not saved.
 */
@Component({
  selector: 'alt-planning-editor',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="head">
      <h3>Planning @if (customised()) {<span class="tag">customised</span>}</h3>
      @if (!draft()) {
        <button class="btn btn-sm" (click)="edit()">Customise</button>
      }
    </div>
    <p class="hint">What the supervisor reads when it chooses agents for a question.</p>

    @if (draft(); as d) {
      @for (f of fields; track f.key) {
        <div class="field">
          <div class="label">
            <label [for]="'pt-' + f.key">{{ f.label }}</label>
            @if (canRevert(f.key)) {
              <button class="link" type="button" (click)="revert(f.key)">use the agent's own</button>
            }
            <span class="count" [class.bad]="!!errors()[f.key]">{{ errors()[f.key] ?? counter(f.key) }}</span>
          </div>
          <textarea class="textarea" [id]="'pt-' + f.key" [rows]="f.rows" [placeholder]="f.hint" [value]="d[f.key]"
                    [class.invalid]="!!errors()[f.key]" (input)="set(f.key, $any($event.target).value)"></textarea>
        </div>
      }
      @if (message(); as m) { <div class="msg">{{ m }}</div> }
      <div class="actions">
        @if (customised()) {
          @if (confirmReset()) {
            <span class="small">Back to the agent's own card?</span>
            <button class="btn btn-sm" (click)="confirmReset.set(false)">No</button>
            <button class="btn btn-sm btn-danger" [disabled]="saving()" (click)="reset()">Reset</button>
          } @else {
            <button class="btn btn-sm btn-ghost" [disabled]="saving()" (click)="confirmReset.set(true)">Reset to agent's card</button>
          }
        }
        <span class="spacer"></span>
        <button class="btn btn-sm" [disabled]="saving()" (click)="cancel()">Cancel</button>
        <button class="btn btn-sm btn-primary" [disabled]="saving() || invalid()" (click)="save()">{{ saving() ? 'Saving…' : 'Save' }}</button>
      </div>
      <p class="note">Saved on the supervisor's machine and used from the next question.</p>
    } @else {
      <dl>
        @for (f of fields; track f.key) {
          <dt>{{ f.label }} @if (agent().overrides[f.key] !== undefined) {<span class="dot" title="customised"></span>}</dt>
          <dd>
            @if (f.key === 'examples') {
              @for (e of current().examples; track $index) { <div>“{{ e }}”</div> } @empty { <span class="faint">—</span> }
            } @else {
              {{ current()[f.key] || '—' }}
            }
          </dd>
        }
      </dl>
      @if (!agent().planning_defaults) {
        <p class="note">The agent's own card is not loaded yet (it is not reachable): customised text applies when it is.</p>
      }
      @if (message(); as m) { <div class="msg ok">{{ m }}</div> }
    }
  `,
  styles: `
    :host { display: block; }
    .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    h3 { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 13px; font-weight: 600; }
    .tag { padding: 0 7px; border-radius: 999px; font-size: 11px; font-weight: 600; background: var(--warn-soft); color: var(--warn); }
    .hint { margin: 2px 0 10px; font-size: 12.5px; color: var(--text-muted); }
    .field { margin-bottom: 12px; }
    .label { display: flex; align-items: baseline; gap: 8px; margin-bottom: 4px; font-size: 12.5px; font-weight: 500; }
    .link { padding: 0; font: inherit; font-size: 12px; font-weight: 400; color: var(--primary); background: none; border: 0; cursor: pointer; }
    .link:hover { text-decoration: underline; }
    .count { margin-left: auto; font-size: 11.5px; font-weight: 400; color: var(--text-faint); font-variant-numeric: tabular-nums; }
    .bad { color: var(--danger); }
    .textarea { min-height: 0; font-size: 13px; line-height: 1.45; }
    .textarea.invalid { border-color: var(--danger); }
    .actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; } .spacer { flex: 1; }
    .small { font-size: 12px; }
    .msg { margin-bottom: 10px; padding: 8px 12px; border-radius: var(--radius-sm); font-size: 12.5px; background: var(--danger-soft);
           color: var(--danger); overflow-wrap: anywhere; }
    .msg.ok { margin: 10px 0 0; background: var(--ok-soft); color: var(--ok); }
    .note { margin: 8px 0 0; font-size: 12px; color: var(--text-faint); }
    dl { display: grid; grid-template-columns: 112px minmax(0, 1fr); gap: 8px 12px; margin: 0; font-size: 13px; }
    dt { display: flex; align-items: baseline; gap: 6px; color: var(--text-muted); }
    dd { margin: 0; overflow-wrap: anywhere; }
    .dot { flex: none; width: 6px; height: 6px; border-radius: 50%; background: var(--warn); transform: translateY(-1px); }
  `,
})
export class PlanningEditor {
  private readonly orchestrator = inject(OrchestratorService);
  readonly agent = input.required<AgentAdmin>();
  readonly saved = output<AgentAdmin>();

  protected readonly fields = FIELDS;
  protected readonly draft = signal<Draft | null>(null);
  protected readonly saving = signal(false);
  protected readonly confirmReset = signal(false);
  protected readonly message = signal<string | null>(null);

  protected readonly customised = computed(() => Object.keys(this.agent().overrides ?? {}).length > 0);

  /** What the supervisor plans with now. */
  protected readonly current = computed<PlanningText>(() => {
    const a = this.agent();
    const own = a.planning_defaults ?? a.card ?? { description: '', when_to_use: '', when_not_to_use: '', examples: [] };
    return { ...own, ...(a.card ?? {}), ...a.overrides } as PlanningText;
  });

  protected readonly errors = computed(() => {
    const d = this.draft();
    const out: Partial<Record<Key, string>> = {};
    if (!d) return out;
    for (const f of FIELDS) {
      if (f.key === 'examples') {
        const ex = lines(d.examples);
        if (ex.length > MAX_EXAMPLES) out.examples = `${ex.length} / ${MAX_EXAMPLES} examples`;
        else if (ex.some((e) => e.length > f.max)) out.examples = `an example is over ${f.max} characters`;
      } else if (d[f.key].trim().length > f.max) {
        out[f.key] = `${d[f.key].trim().length} / ${f.max}`;
      }
    }
    return out;
  });
  protected readonly invalid = computed(() => Object.keys(this.errors()).length > 0);

  protected edit(): void {
    const now = this.current();
    this.draft.set(Object.fromEntries(FIELDS.map((f) => [f.key, asText(now[f.key])])) as Draft);
    this.message.set(null);
  }

  protected cancel(): void {
    this.draft.set(null);
    this.confirmReset.set(false);
    this.message.set(null);
  }

  protected set(key: Key, value: string): void {
    this.draft.update((d) => d && { ...d, [key]: value });
  }

  protected canRevert(key: Key): boolean {
    const own = this.agent().planning_defaults;
    const d = this.draft();
    return !!own && !!d && !same(key, d[key], asText(own[key]));
  }

  protected revert(key: Key): void {
    const own = this.agent().planning_defaults;
    if (own) this.set(key, asText(own[key]));
  }

  protected counter(key: Key): string {
    const d = this.draft();
    if (!d) return '';
    if (key === 'examples') return `${lines(d.examples).length} / ${MAX_EXAMPLES}`;
    return `${d[key].trim().length} / ${FIELDS.find((f) => f.key === key)!.max}`;
  }

  /** Only what differs from the agent's own card (an empty field: the agent's own). */
  protected async save(): Promise<void> {
    const d = this.draft();
    if (!d) return;
    const own = this.agent().planning_defaults;
    const text: Partial<PlanningText> = {};
    for (const f of FIELDS) {
      if (!d[f.key].trim() || (own && same(f.key, d[f.key], asText(own[f.key])))) continue;
      if (f.key === 'examples') text.examples = lines(d.examples);
      else text[f.key] = d[f.key].trim();
    }
    await this.call(() => this.orchestrator.customiseAgent(this.agent().name, text),
      Object.keys(text).length ? 'Saved. The supervisor plans with it from the next question.' : "Saved: the agent's own card.");
  }

  protected async reset(): Promise<void> {
    this.confirmReset.set(false);
    await this.call(() => this.orchestrator.customiseAgent(this.agent().name, null), "Back to the agent's own card.");
  }

  private async call(request: () => Promise<AgentAdmin>, done: string): Promise<void> {
    this.saving.set(true);
    this.message.set(null);
    try {
      this.saved.emit(await request());
      this.draft.set(null);
      this.message.set(done);
    } catch (err) {
      this.message.set(`Not saved: ${err instanceof Error ? err.message : err}`);
    } finally {
      this.saving.set(false);
    }
  }
}
