import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { AgentCard, AgentCardView, agentApiUrl } from '@altasnim/shared';

/** GET /custom/status: how email is configured (never the password). */
interface EmailStatus {
  delivery: 'smtp' | 'console';
  smtp_host: string | null;
  smtp_port: number;
  security: 'starttls' | 'ssl' | 'none';
  smtp_username: string | null;
  password_set: boolean;
  from: string | null;
  from_name: string;
  reply_to: string | null;
  allowed_domains: string[];
  max_recipients: number;
  llm_model: string | null;
  ready: boolean;
  missing: string[];
}

/** GET /custom/sent: one email sent (or logged) since the agent started. */
interface SentEmail {
  message_id: string;
  to: string[];
  cc: string[];
  subject: string;
  delivery: 'smtp' | 'console';
  writer: 'llm' | 'template';
  at: string;
}

const POLL_MS = 5000;

/** Team Comms' own page: the email setup, the emails sent, and the agent's card (its own custom routes only). */
@Component({
  selector: 'alt-communication-page',
  imports: [AgentCardView],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page stack">
      <div>
        <h1>Communication agent</h1>
        <p class="muted">
          Writes a professional email from the results of earlier steps (only their facts), asks a human to approve
          it, then sends it.
        </p>
      </div>

      @if (error(); as err) {
        <div class="card error">{{ err }}</div>
      }

      @if (status(); as s) {
        <div class="card stack">
          <div class="row head">
            <h2>Email setup</h2>
            <span class="badge" [class.ok]="s.ready" [class.warn]="!s.ready">
              {{ s.ready ? (s.delivery === 'smtp' ? 'Ready to send' : 'Test mode: emails are only logged') : 'Not configured' }}
            </span>
          </div>
          @if (s.missing.length) {
            <p class="warn-text">Set in backend/.env: {{ s.missing.join(', ') }}</p>
          }
          <dl class="grid">
            <dt>Delivery</dt><dd>{{ s.delivery === 'smtp' ? 'SMTP (sends)' : 'Console (logs only)' }}</dd>
            <dt>Sender</dt><dd>{{ s.from_name }} &lt;{{ s.from ?? 'not set' }}&gt;</dd>
            <dt>Mail server</dt><dd>{{ s.smtp_host ?? 'not set' }}:{{ s.smtp_port }} · {{ s.security }}</dd>
            <dt>Login</dt><dd>{{ s.smtp_username ?? 'none' }} · password {{ s.password_set ? 'set' : 'not set' }}</dd>
            <dt>Writer</dt><dd>{{ s.llm_model ? 'LLM ' + s.llm_model + ' (facts checked)' : 'Template (no LLM)' }}</dd>
            <dt>Recipients</dt>
            <dd>
              {{ s.allowed_domains.length ? 'only ' + s.allowed_domains.join(', ') : 'any domain' }} · at most
              {{ s.max_recipients }}
            </dd>
            @if (s.reply_to) {
              <dt>Reply-To</dt><dd>{{ s.reply_to }}</dd>
            }
          </dl>
        </div>
      }

      <div class="card stack">
        <h2>Emails sent <span class="muted small">(since the agent started)</span></h2>
        @if (sent().length) {
          <table class="table">
            <thead>
              <tr><th>When</th><th>Subject</th><th>To</th><th>Delivery</th><th>Written by</th></tr>
            </thead>
            <tbody>
              @for (e of sent(); track e.message_id) {
                <tr>
                  <td class="nowrap">{{ e.at.slice(0, 19).replace('T', ' ') }}</td>
                  <td>{{ e.subject }}</td>
                  <td>{{ e.to.join(', ') }}@if (e.cc.length) {<span class="muted"> · cc {{ e.cc.join(', ') }}</span>}</td>
                  <td>{{ e.delivery === 'smtp' ? 'sent' : 'logged' }}</td>
                  <td>{{ e.writer === 'llm' ? 'LLM' : 'template' }}</td>
                </tr>
              }
            </tbody>
          </table>
        } @else {
          <p class="muted">No email yet. Ask the Assistant, e.g. "Find the iPhone 16 price in Oman and email it to …".</p>
        }
      </div>

      @if (card(); as c) {
        <alt-agent-card [card]="c" />
      }
    </div>
  `,
  styles: `
    .error { border-color: var(--danger); background: var(--danger-soft); color: var(--danger); }
    .head { justify-content: space-between; align-items: center; }
    .badge { font-size: 12px; padding: 2px 10px; border-radius: 999px; border: 1px solid var(--border); }
    .badge.ok { color: var(--ok); border-color: var(--ok); }
    .badge.warn { color: var(--warn, #b45309); border-color: var(--warn, #b45309); }
    .warn-text { color: var(--warn, #b45309); margin: 0; }
    .grid { display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; margin: 0; }
    .grid dt { color: var(--muted); }
    .grid dd { margin: 0; overflow-wrap: anywhere; }
    .table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .table th, .table td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }
    .nowrap { white-space: nowrap; }
    .small { font-size: 12px; font-weight: normal; }
  `,
})
export class CommunicationPage {
  private readonly api = agentApiUrl('communication');
  protected readonly card = signal<AgentCard | null>(null);
  protected readonly status = signal<EmailStatus | null>(null);
  protected readonly sent = signal<SentEmail[]>([]);
  protected readonly error = signal<string | null>(null);

  constructor() {
    this.load();
    const timer = setInterval(() => this.refresh(), POLL_MS);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  private async load(): Promise<void> {
    try {
      const res = await fetch(`${this.api}/card`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.card.set(await res.json());
      await this.refresh();
    } catch (err) {
      this.error.set(`The communication agent is not reachable (${this.api}): ${(err as Error).message ?? err}`);
    }
  }

  private async refresh(): Promise<void> {
    const [status, sent] = await Promise.all([fetch(`${this.api}/custom/status`), fetch(`${this.api}/custom/sent`)]);
    if (status.ok) this.status.set(await status.json());
    if (sent.ok) this.sent.set(await sent.json());
    if (status.ok) this.error.set(null);
  }
}
