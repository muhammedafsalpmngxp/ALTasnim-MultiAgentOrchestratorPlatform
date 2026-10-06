import { ChangeDetectionStrategy, Component, computed, inject, input, linkedSignal, output, signal } from '@angular/core';
import { OrchestratorService, PlatformPolicies } from '@altasnim/shared';

type NumberKey = 'max_steps' | 'max_replans' | 'max_clarifications';
type ToggleKey = 'verify_final';

/** Same ranges as the supervisor's Policies model (settings.py): it rejects anything else. */
const LIMITS: { key: NumberKey; label: string; hint: string; min: number; max: number }[] = [
  { key: 'max_steps', label: 'Steps per plan', hint: 'The most steps the supervisor may plan for one question.', min: 1, max: 50 },
  { key: 'max_replans', label: 'Replans', hint: 'How often it may try another way after a source fails or is rejected (e.g. rag, then web search).', min: 0, max: 10 },
  { key: 'max_clarifications', label: 'Clarifying questions', hint: 'How often it may ask the user before it plans.', min: 0, max: 10 },
];

const CHECKS: { key: ToggleKey; label: string; hint: string }[] = [
  { key: 'verify_final', label: 'Check every answer', hint: 'The verifier checks that each final answer matches what the user asked. A failed check sends the supervisor back to write the answer again.' },
];

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const DOMAIN_RE = /^[a-z0-9-]+(\.[a-z0-9-]+)+$/;

/** The supervisor's safety rules, edited at runtime: in force for every next step, until reset or a restart. */
@Component({
  selector: 'alt-admin-policies',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (draft(); as d) {
      <div class="note">
        <strong>Changes apply at once</strong> to every next step of every run, until <em>Reset to file</em> or the
        supervisor restarts. To keep them, also change <span class="mono">config/policies.yaml</span>.
      </div>

      <section class="card">
        <h2>Limits</h2>
        @for (f of limits; track f.key) {
          <div class="field">
            <div class="text">
              <label [for]="f.key">{{ f.label }} @if (changed(f.key)) {<span class="mod">changed</span>}</label>
              <p>{{ f.hint }}</p>
            </div>
            <div class="ctl">
              <div class="stepper" [class.invalid]="!!errors()[f.key]">
                <button type="button" (click)="bump(f.key, -1)" [disabled]="d[f.key] <= f.min" aria-label="Less">−</button>
                <input [id]="f.key" type="number" inputmode="numeric" [min]="f.min" [max]="f.max" [value]="d[f.key]"
                       (input)="setNumber(f.key, $any($event.target).value)" />
                <button type="button" (click)="bump(f.key, 1)" [disabled]="d[f.key] >= f.max" aria-label="More">+</button>
              </div>
              <span class="range" [class.bad]="!!errors()[f.key]">{{ errors()[f.key] ?? f.min + '–' + f.max }}</span>
            </div>
          </div>
        }
      </section>

      <section class="card">
        <h2>Verification</h2>
        @for (f of checks; track f.key) {
          <div class="field">
            <div class="text">
              <label [for]="f.key">{{ f.label }} @if (changed(f.key)) {<span class="mod">changed</span>}</label>
              <p>{{ f.hint }}</p>
            </div>
            <label class="toggle">
              <input [id]="f.key" type="checkbox" role="switch" [checked]="d[f.key]" (change)="set(f.key, $any($event.target).checked)" />
              <span class="track"></span><span class="state">{{ d[f.key] ? 'On' : 'Off' }}</span>
            </label>
          </div>
        }
      </section>

      <section class="card">
        <h2>Email recipients @if (changed('allowed_email_domains')) {<span class="mod">changed</span>}</h2>
        <p class="hint">The communication agent may only email these domains. None: any domain (development only).</p>
        <div class="domains">
          @for (domain of d.allowed_email_domains; track domain) {
            <span class="domain">{{ domain }}<button type="button" (click)="removeDomain(domain)" [attr.aria-label]="'Remove ' + domain">✕</button></span>
          } @empty {
            <span class="any">Any domain</span>
          }
        </div>
        <div class="add">
          <input class="input" placeholder="example.com" aria-label="Domain to allow" [value]="domain()"
                 (input)="domain.set($any($event.target).value)" (keydown.enter)="addDomain()" />
          <button class="btn btn-sm" type="button" [disabled]="!domain().trim()" (click)="addDomain()">Add domain</button>
        </div>
        @if (domainError(); as err) { <p class="bad small">{{ err }}</p> }
      </section>

      @if (message(); as m) {
        <div class="msg" [class.ok]="m.ok" role="status">{{ m.text }}</div>
      }

      <div class="bar" [class.dirty]="dirty()">
        <span class="muted">{{ dirty() ? changes() + ' unsaved change' + (changes() === 1 ? '' : 's') : 'Policies are in force' }}</span>
        <span class="spacer"></span>
        @if (confirmReset()) {
          <span class="small">Reset every policy to config/policies.yaml?</span>
          <button class="btn btn-sm" (click)="confirmReset.set(false)">Cancel</button>
          <button class="btn btn-sm btn-danger" [disabled]="saving()" (click)="reset()">Reset</button>
        } @else {
          <button class="btn btn-sm btn-ghost" [disabled]="saving()" (click)="confirmReset.set(true)">Reset to file</button>
          <button class="btn btn-sm" [disabled]="!dirty() || saving()" (click)="discard()">Discard</button>
          <button class="btn btn-sm btn-primary" [disabled]="!dirty() || invalid() || saving()" (click)="save()">
            {{ saving() ? 'Saving…' : 'Save changes' }}
          </button>
        }
      </div>
    } @else {
      <div class="card muted">Loading policies…</div>
    }
  `,
  styles: `
    :host { display: flex; flex-direction: column; gap: 16px; max-width: 920px; }
    .mono { font-family: var(--mono); font-size: 12.5px; } .small { font-size: 12px; } .bad { color: var(--danger); }
    .note { padding: 10px 14px; border-radius: var(--radius-sm); background: var(--info-soft); color: var(--text); font-size: 13px; }
    .card > h2 { display: flex; align-items: center; gap: 8px; }
    .field { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 14px 0; border-top: 1px solid var(--border); }
    h2 + .field { border-top: 0; padding-top: 4px; }
    .text { min-width: 0; } .text label { display: flex; align-items: center; gap: 8px; font-weight: 500; }
    .text p, .hint { margin: 2px 0 0; font-size: 12.5px; color: var(--text-muted); }
    .mod { padding: 0 7px; border-radius: 999px; font-size: 11px; font-weight: 600; background: var(--warn-soft); color: var(--warn); }
    .ctl { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex: none; }
    .stepper { display: inline-flex; height: 34px; border: 1px solid var(--border-strong); border-radius: var(--radius-sm); overflow: hidden; background: var(--surface); }
    .stepper:focus-within { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-soft); }
    .stepper.invalid { border-color: var(--danger); }
    .stepper button { width: 32px; font: inherit; font-size: 16px; color: var(--text-muted); background: var(--surface-2); border: 0; cursor: pointer; }
    .stepper button:hover:not(:disabled) { color: var(--text); background: var(--surface-3); } .stepper button:disabled { opacity: 0.4; cursor: default; }
    .stepper input { width: 52px; font: inherit; font-weight: 600; text-align: center; color: var(--text); background: none; border: 0; outline: none;
                     font-variant-numeric: tabular-nums; appearance: textfield; -moz-appearance: textfield; }
    .stepper input::-webkit-inner-spin-button, .stepper input::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
    .range { font-size: 11.5px; color: var(--text-faint); }
    .toggle { display: inline-flex; align-items: center; gap: 8px; flex: none; cursor: pointer; }
    .toggle input { position: absolute; opacity: 0; pointer-events: none; }
    .track { position: relative; width: 36px; height: 20px; border-radius: 999px; background: var(--border-strong); transition: background 0.2s; }
    .track::after { content: ''; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: #fff;
                    box-shadow: var(--shadow-sm); transition: transform 0.2s; }
    .toggle input:checked + .track { background: var(--primary); } .toggle input:checked + .track::after { transform: translateX(16px); }
    .toggle input:focus-visible + .track { outline: 2px solid var(--focus); outline-offset: 2px; }
    .state { width: 24px; font-size: 12.5px; color: var(--text-muted); }
    .domains { display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0; }
    .domain { display: inline-flex; align-items: center; gap: 4px; padding: 3px 4px 3px 10px; border-radius: 999px; font-family: var(--mono);
              font-size: 12.5px; background: var(--primary-soft); color: var(--primary); }
    .domain button { width: 20px; height: 20px; font-size: 10px; color: inherit; background: none; border: 0; border-radius: 50%; cursor: pointer; }
    .domain button:hover { background: color-mix(in srgb, var(--primary) 15%, transparent); }
    .any { font-size: 12.5px; color: var(--warn); }
    .add { display: flex; gap: 8px; max-width: 420px; } .add .input { height: 30px; }
    .msg { padding: 9px 14px; border-radius: var(--radius-sm); font-size: 13px; background: var(--danger-soft); color: var(--danger); }
    .msg.ok { background: var(--ok-soft); color: var(--ok); }
    .bar { position: sticky; bottom: 12px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 14px;
           border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); box-shadow: var(--shadow); transition: box-shadow 0.2s, border-color 0.2s; }
    .bar.dirty { border-color: var(--primary); box-shadow: var(--shadow-lg); }
    .spacer { flex: 1; }
    @media (max-width: 560px) { .field { flex-direction: column; align-items: flex-start; gap: 10px; } .ctl { align-items: flex-start; } }
  `,
})
export class PoliciesTab {
  private readonly orchestrator = inject(OrchestratorService);
  readonly policies = input<PlatformPolicies | null>(null);
  readonly saved = output<PlatformPolicies>();

  protected readonly limits = LIMITS;
  protected readonly checks = CHECKS;

  /** The form. A refresh from the supervisor replaces it only while nothing is edited. */
  protected readonly draft = linkedSignal<PlatformPolicies | null, PlatformPolicies | null>({
    source: this.policies,
    computation: (policies, previous) =>
      previous?.value && !same(previous.value, previous.source) ? previous.value : policies && structuredClone(policies),
  });

  protected readonly domain = signal('');
  protected readonly domainError = signal<string | null>(null);
  protected readonly saving = signal(false);
  protected readonly confirmReset = signal(false);
  protected readonly message = signal<{ ok: boolean; text: string } | null>(null);

  protected readonly dirty = computed(() => !!this.draft() && !same(this.draft(), this.policies()));
  protected readonly changes = computed(() => {
    const d = this.draft(), p = this.policies();
    return d && p ? (Object.keys(d) as (keyof PlatformPolicies)[]).filter((k) => !same(d[k], p[k])).length : 0;
  });

  protected readonly errors = computed(() => {
    const d = this.draft();
    const out: Partial<Record<NumberKey, string>> = {};
    for (const f of LIMITS) {
      const v = d?.[f.key];
      if (v == null || !Number.isInteger(v) || v < f.min || v > f.max) out[f.key] = `${f.min}–${f.max} only`;
    }
    return out;
  });
  protected readonly invalid = computed(() => Object.keys(this.errors()).length > 0);

  protected changed(key: keyof PlatformPolicies): boolean {
    const d = this.draft(), p = this.policies();
    return !!d && !!p && !same(d[key], p[key]);
  }

  protected set<K extends keyof PlatformPolicies>(key: K, value: PlatformPolicies[K]): void {
    this.draft.update((d) => d && { ...d, [key]: value });
    this.message.set(null);
  }

  protected setNumber(key: NumberKey, raw: string): void {
    this.set(key, raw === '' ? (NaN as number) : Number(raw));
  }

  protected bump(key: NumberKey, by: number): void {
    const f = LIMITS.find((l) => l.key === key)!;
    const v = this.draft()?.[key];
    this.set(key, Math.min(f.max, Math.max(f.min, (Number.isFinite(v) ? v! : f.min) + by)));
  }

  protected addDomain(): void {
    const domain = this.domain().trim().toLowerCase().replace(/^@/, '');
    if (!DOMAIN_RE.test(domain)) {
      this.domainError.set(`“${domain}” is not a domain (like example.com).`);
      return;
    }
    const list = this.draft()?.allowed_email_domains ?? [];
    if (!list.includes(domain)) this.set('allowed_email_domains', [...list, domain]);
    this.domain.set('');
    this.domainError.set(null);
  }

  protected removeDomain(domain: string): void {
    this.set('allowed_email_domains', (this.draft()?.allowed_email_domains ?? []).filter((d) => d !== domain));
  }

  protected discard(): void {
    const p = this.policies();
    this.draft.set(p && structuredClone(p));
    this.message.set(null);
  }

  protected async save(): Promise<void> {
    const draft = this.draft();
    if (!draft) return;
    await this.run(() => this.orchestrator.updatePolicies(draft), 'Saved. The supervisor uses the new policies from its next step.');
  }

  protected async reset(): Promise<void> {
    this.confirmReset.set(false);
    await this.run(() => this.orchestrator.resetPolicies(), 'Reset to config/policies.yaml.');
  }

  private async run(call: () => Promise<PlatformPolicies>, done: string): Promise<void> {
    this.saving.set(true);
    try {
      const policies = await call();
      this.draft.set(structuredClone(policies));
      this.saved.emit(policies);
      this.message.set({ ok: true, text: done });
    } catch (err) {
      this.message.set({ ok: false, text: `Not saved: ${err instanceof Error ? err.message : err}` });
    } finally {
      this.saving.set(false);
    }
  }
}
