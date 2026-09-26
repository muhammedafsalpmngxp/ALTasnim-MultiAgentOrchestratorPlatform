import { ChangeDetectionStrategy, Component, computed, effect, input, signal } from '@angular/core';

interface EmailDraft {
  to: string[];
  subject: string;
  body: string;
}

type Decision =
  | { action: 'approve' }
  | { action: 'edit'; edited: EmailDraft }
  | { action: 'reject'; reason: string };

/**
 * Approval form for the communication agent's interrupt (kind: "email_approval").
 * The platform renders it inside Multi Agent Flow / Approvals and passes `request` + `decide`.
 * Resume values match backend/communication-agent/src/communication_agent/nodes/approve.py.
 */
@Component({
  selector: 'alt-email-approval-form',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="form stack">
      <label class="field">To (comma separated)
        <input class="input" [value]="to()" (input)="to.set($any($event.target).value)" />
      </label>
      <label class="field">Subject
        <input class="input" [value]="subject()" (input)="subject.set($any($event.target).value)" />
      </label>
      <label class="field">Body
        <textarea class="textarea" [value]="body()" (input)="body.set($any($event.target).value)"></textarea>
      </label>
      <div class="row">
        <button class="btn btn-primary" (click)="approve()" [disabled]="submitted()">
          {{ edited() ? 'Send edited email' : 'Approve & send' }}
        </button>
        <button class="btn btn-danger" (click)="reject()" [disabled]="submitted()">Reject</button>
        @if (edited()) {
          <span class="muted small">edited</span>
        }
      </div>
    </div>
  `,
  styles: `.small { font-size: 12px; } .form { margin-top: 8px; }`,
})
export class EmailApprovalForm {
  /** The agent's interrupt payload: { kind: 'email_approval', draft: {to, subject, body} } */
  readonly request = input<{ draft?: EmailDraft } | null>(null);
  readonly decide = input<(decision: Decision) => void>(() => undefined);

  protected readonly to = signal('');
  protected readonly subject = signal('');
  protected readonly body = signal('');
  protected readonly submitted = signal(false);

  private readonly original = computed<EmailDraft>(() => this.request()?.draft ?? { to: [], subject: '', body: '' });
  protected readonly edited = computed(() => {
    const o = this.original();
    return this.to() !== o.to.join(', ') || this.subject() !== o.subject || this.body() !== o.body;
  });

  constructor() {
    effect(() => {
      const d = this.original();
      this.to.set(d.to.join(', '));
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
    const to = this.to().split(',').map((s) => s.trim()).filter(Boolean);
    this.decide()({ action: 'edit', edited: { to, subject: this.subject(), body: this.body() } });
  }

  protected reject(): void {
    this.submitted.set(true);
    this.decide()({ action: 'reject', reason: 'rejected by approver' });
  }
}
