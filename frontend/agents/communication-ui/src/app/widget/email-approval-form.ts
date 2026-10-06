import { ChangeDetectionStrategy, Component, computed, effect, input, signal } from '@angular/core';

interface EmailDraft {
  to: string[];
  cc?: string[];
  subject: string;
  body: string;
  sources?: string[];
  writer?: 'llm' | 'template';
  grounded?: boolean;
}

type Decision =
  | { action: 'approve' }
  | { action: 'edit'; edited: Pick<EmailDraft, 'to' | 'cc' | 'subject' | 'body'> }
  | { action: 'reject'; reason: string };

const split = (value: string) => value.split(',').map((s) => s.trim()).filter(Boolean);

/**
 * Approval form for the communication agent's interrupt (kind: "email_approval").
 * The platform renders it inside Multi Agent Flow / Approvals and passes `request` + `decide`.
 * Resume values match backend/communication_agent/src/communication_agent/nodes/approve.py.
 */
@Component({
  selector: 'alt-email-approval-form',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="form stack">
      <div class="row tags">
        <span class="tag">{{ original().writer === 'llm' ? 'Written by the LLM' : 'Written from a template' }}</span>
        @if (original().grounded !== false) {
          <span class="tag ok">Every number and link checked against the results</span>
        }
      </div>
      <label class="field">To (comma separated)
        <input class="input" [value]="to()" (input)="to.set($any($event.target).value)" />
      </label>
      <label class="field">Cc (comma separated, optional)
        <input class="input" [value]="cc()" (input)="cc.set($any($event.target).value)" />
      </label>
      <label class="field">Subject
        <input class="input" [value]="subject()" (input)="subject.set($any($event.target).value)" />
      </label>
      <label class="field">Email
        <textarea class="textarea body" [value]="body()" (input)="body.set($any($event.target).value)"></textarea>
      </label>
      <p class="muted small">The recipient gets this as a formatted email (HTML) with the same text.</p>
      <div class="row">
        <button class="btn btn-primary" (click)="approve()" [disabled]="submitted() || !to().trim()">
          {{ edited() ? 'Send edited email' : 'Approve & send' }}
        </button>
        <button class="btn btn-danger" (click)="reject()" [disabled]="submitted()">Reject</button>
        @if (edited()) {
          <span class="muted small">edited</span>
        }
      </div>
    </div>
  `,
  styles: `
    .small { font-size: 12px; margin: 0; }
    .form { margin-top: 8px; }
    .body { min-height: 260px; font-family: inherit; line-height: 1.5; }
    .tags { gap: 6px; flex-wrap: wrap; }
    .tag { font-size: 12px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border); color: var(--muted); }
    .tag.ok { color: var(--ok); border-color: var(--ok); }
  `,
})
export class EmailApprovalForm {
  /** The agent's interrupt payload: { kind: 'email_approval', draft: {to, cc, subject, body, ...} } */
  readonly request = input<{ draft?: EmailDraft } | null>(null);
  readonly decide = input<(decision: Decision) => void>(() => undefined);

  protected readonly to = signal('');
  protected readonly cc = signal('');
  protected readonly subject = signal('');
  protected readonly body = signal('');
  protected readonly submitted = signal(false);

  protected readonly original = computed<EmailDraft>(
    () => this.request()?.draft ?? { to: [], cc: [], subject: '', body: '' },
  );
  protected readonly edited = computed(() => {
    const o = this.original();
    return (
      this.to() !== o.to.join(', ') ||
      this.cc() !== (o.cc ?? []).join(', ') ||
      this.subject() !== o.subject ||
      this.body() !== o.body
    );
  });

  constructor() {
    effect(() => {
      const d = this.original();
      this.to.set(d.to.join(', '));
      this.cc.set((d.cc ?? []).join(', '));
      this.subject.set(d.subject);
      this.body.set(d.body);
      this.submitted.set(false);
    });
  }

  protected approve(): void {
    this.submitted.set(true);
    if (!this.edited()) {
      this.decide()({ action: 'approve' });
      return;
    }
    this.decide()({
      action: 'edit',
      edited: { to: split(this.to()), cc: split(this.cc()), subject: this.subject(), body: this.body() },
    });
  }

  protected reject(): void {
    this.submitted.set(true);
    this.decide()({ action: 'reject', reason: 'rejected by approver' });
  }
}
