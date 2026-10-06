import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { AgentCard, AgentCardView, agentApiUrl } from '@altasnim/shared';

import { CallDetail } from './calls/call-detail';
import { CallList } from './calls/call-list';
import { VerifyCallsStore } from './calls/verify-calls.store';
import { timeAgo } from './calls/verify-call';

type Tab = 'calls' | 'agent';

/** Team Quality's own page: the platform's checks (verdicts) + the agent card. Always light, whatever the OS theme. */
@Component({
  selector: 'alt-verifier-page',
  imports: [AgentCardView, CallList, CallDetail],
  providers: [VerifyCallsStore],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="top">
      <div class="brand">
        <div class="logo" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M12 2 4 5v6c0 5 3.4 9.7 8 11 4.6-1.3 8-6 8-11V5l-8-3Zm-1.2 14.2-3.5-3.5 1.4-1.4 2.1 2.1 4.9-4.9 1.4 1.4-6.3 6.3Z"/></svg>
        </div>
        <div>
          <h1>Verifier</h1>
          <p>team-quality · :8203{{ card()?.version ? ' · v' + card()!.version : '' }}</p>
        </div>
      </div>
      <nav class="tabs" role="tablist">
        <button type="button" role="tab" [class.on]="tab() === 'calls'" [attr.aria-selected]="tab() === 'calls'" (click)="tab.set('calls')">
          Calls @if (store.calls().length) { <span class="count">{{ store.calls().length }}</span> }
        </button>
        <button type="button" role="tab" [class.on]="tab() === 'agent'" [attr.aria-selected]="tab() === 'agent'" (click)="tab.set('agent')">Agent</button>
      </nav>
      <div class="live" [attr.data-state]="liveState()">
        <span class="pulse"></span>{{ liveLabel() }}
      </div>
    </header>

    @if (tab() === 'calls') {
      <section class="kpis">
        <div class="kpi"><span>Calls</span><strong>{{ s().total }}</strong><em>{{ lastSeen() }}</em></div>
        <div class="kpi"><span>Passed</span><strong class="ok">{{ s().passed }}</strong><em>verified</em></div>
        <div class="kpi"><span>Failed</span><strong class="bad">{{ s().failed }}</strong><em>need replan</em></div>
        <div class="kpi">
          <span>Pass rate</span><strong>{{ s().passRate != null ? s().passRate + '%' : '—' }}</strong>
          <div class="meter"><i [style.width.%]="s().passRate ?? 0"></i></div>
        </div>
        <div class="kpi"><span>Avg. time</span><strong>{{ s().avgMs != null ? s().avgMs + ' ms' : '—' }}</strong><em>per check</em></div>
        <div class="kpi"><span>Rewrites</span><strong>{{ s().rewrites }}</strong><em>answers sent back</em></div>
      </section>

      @if (store.calls().length) {
        <div class="workspace">
          <aside class="pane list">
            <vf-call-list />
            <footer class="lf">
              <button type="button" class="link" (click)="clear()">Clear history</button>
              <span>in memory · last 50</span>
            </footer>
          </aside>
          <main class="pane detail">
            @if (store.selected(); as c) {
              <vf-call-detail [call]="c" />
            } @else {
              <div class="empty small">No call matches your filter.</div>
            }
          </main>
        </div>
      } @else {
        <div class="pane empty">
          <div class="radar" aria-hidden="true"><span></span><span></span><span></span>
            <svg viewBox="0 0 24 24"><path d="M12 2 4 5v6c0 5 3.4 9.7 8 11 4.6-1.3 8-6 8-11V5l-8-3Z"/></svg>
          </div>
          <h2>{{ store.connected() === false ? 'Verifier not reachable' : 'Waiting for the first call' }}</h2>
          @if (store.connected() === false) {
            <p>Start the verifier on port 8203 (<code>docker compose up verifier-agent</code>). This page reconnects on its own.</p>
          } @else {
            <p>Every check the platform runs shows up here within a few seconds: the question, the answer and the
              verdict. Ask a question in the shell (http://localhost:4200) to see one.</p>
          }
        </div>
      }
    } @else {
      <div class="agent">
        @if (cardError(); as err) {
          <div class="pane note bad">{{ err }}</div>
        }
        @if (card(); as c) {
          <alt-agent-card [card]="c" />
        }
        <div class="pane note">
          <h2>When it runs</h2>
          <p>Run by the platform, never planned by the supervisor's LLM: after every final answer. It checks only that the answer matches the user's question
            (every part answered, same topic), in one LLM call: no sources, no fact checking, no searching. A failed
            check sends the supervisor back to write the answer again, up to <code>SUPERVISOR_MAX_REPLANS</code> times.</p>
        </div>
        <div class="pane note">
          <h2>Endpoints</h2>
          <table>
            <tr><td><code>GET /verify/calls</code></td><td>Recent verdicts (this page)</td></tr>
            <tr><td><code>GET /verify/status</code></td><td>The checking model (<code>VERIFIER_LLM_MODEL</code>)</td></tr>
            <tr><td><code>GET /card</code></td><td>Agent card</td></tr>
            <tr><td><code>POST /runs/wait</code></td><td>LangGraph run, used by the orchestrator</td></tr>
          </table>
        </div>
      </div>
    }
  `,
  styles: `
    /* Fixed light palette: this page stays white even when the OS/shell is in dark mode. */
    :host {
      --bg: #f7f8fb; --surface: #ffffff; --surface-2: #f2f4f7; --border: #e4e7ec;
      --text: #101828; --text-muted: #667085;
      --primary: #3d5bd9; --primary-soft: #eef1fd;
      --ok: #067647; --ok-soft: #ecfdf3; --warn: #b54708; --warn-soft: #fffaeb; --danger: #c01048; --danger-soft: #fff1f3;
      color-scheme: light;
      display: flex; flex-direction: column; gap: 18px; min-height: 100%;
      padding: 24px 28px; background: var(--bg); color: var(--text);
      font: 14px/1.5 "Inter", "Segoe UI", system-ui, -apple-system, Roboto, sans-serif;
    }
    code, pre { font-family: ui-monospace, "Cascadia Code", Consolas, monospace; }

    .top { display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
    .brand { display: flex; align-items: center; gap: 12px; }
    .logo { width: 40px; height: 40px; border-radius: 11px; display: grid; place-items: center;
            background: linear-gradient(135deg, #4f6ef0, #3148c4); box-shadow: 0 4px 12px rgba(61, 91, 217, .28); }
    .logo svg { width: 22px; height: 22px; fill: #fff; }
    h1 { margin: 0; font-size: 19px; font-weight: 700; letter-spacing: -.01em; }
    .brand p { margin: 0; font-size: 12.5px; color: var(--text-muted); }
    .tabs { display: flex; gap: 2px; background: var(--surface-2); padding: 3px; border-radius: 9px; }
    .tabs button { font: inherit; font-weight: 550; font-size: 13px; border: 0; background: transparent; color: var(--text-muted);
                   padding: 6px 14px; border-radius: 7px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
    .tabs button.on { background: var(--surface); color: var(--text); box-shadow: 0 1px 2px rgba(16, 24, 40, .1); }
    .count { font-size: 11px; font-weight: 700; background: var(--primary-soft); color: var(--primary); border-radius: 999px; padding: 0 7px; }
    .live { margin-left: auto; display: inline-flex; align-items: center; gap: 8px; font-size: 12.5px; font-weight: 550;
            padding: 6px 12px; border-radius: 999px; background: var(--surface); border: 1px solid var(--border); color: var(--text-muted); }
    .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--text-muted); }
    .live[data-state='on'] { color: var(--ok); }
    .live[data-state='on'] .pulse { background: var(--ok); animation: pulse 2s infinite; }
    .live[data-state='off'] { color: var(--danger); }
    .live[data-state='off'] .pulse { background: var(--danger); }
    @keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(6, 118, 71, .45); } 70% { box-shadow: 0 0 0 7px rgba(6, 118, 71, 0); } 100% { box-shadow: 0 0 0 0 rgba(6, 118, 71, 0); } }

    .kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
    .kpi { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px;
           box-shadow: 0 1px 2px rgba(16, 24, 40, .04); display: flex; flex-direction: column; min-width: 0; }
    .kpi span { font-size: 12px; font-weight: 550; color: var(--text-muted); }
    .kpi strong { font-size: 24px; font-weight: 700; letter-spacing: -.02em; margin-top: 2px; font-variant-numeric: tabular-nums; }
    .kpi strong.ok { color: var(--ok); }
    .kpi strong.bad { color: var(--danger); }
    .kpi em { font-style: normal; font-size: 12px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .meter { height: 5px; border-radius: 5px; background: var(--danger-soft); margin-top: 8px; overflow: hidden; }
    .meter i { display: block; height: 100%; background: var(--ok); border-radius: 5px; transition: width .4s; }

    .pane { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: 0 1px 3px rgba(16, 24, 40, .05); }
    .workspace { display: grid; grid-template-columns: 340px minmax(0, 1fr); gap: 14px; flex: 1; min-height: 560px; height: calc(100vh - 240px); }
    .list { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
    .list vf-call-list { flex: 1; }
    .lf { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; border-top: 1px solid var(--border);
          font-size: 12px; color: var(--text-muted); }
    .link { font: inherit; font-size: 12px; font-weight: 550; border: 0; background: none; color: var(--danger); cursor: pointer; padding: 0; }
    .link:hover { text-decoration: underline; }
    .detail { overflow-y: auto; min-height: 0; }

    .empty { display: flex; flex-direction: column; align-items: center; text-align: center; padding: 64px 24px; }
    .empty.small { padding: 48px; color: var(--text-muted); border: 0; box-shadow: none; }
    .empty h2 { margin: 22px 0 6px; font-size: 18px; }
    .empty p { margin: 0; max-width: 520px; color: var(--text-muted); }
    .empty pre { margin: 20px 0 0; text-align: left; font-size: 12px; background: var(--surface-2); border: 1px solid var(--border);
                 border-radius: 10px; padding: 14px 16px; max-width: 100%; overflow-x: auto; }
    .empty code, .note code { background: var(--surface-2); padding: 1px 6px; border-radius: 4px; font-size: 12px; }
    .radar { position: relative; width: 84px; height: 84px; display: grid; place-items: center; }
    .radar span { position: absolute; inset: 0; border-radius: 50%; border: 2px solid var(--primary); opacity: 0; animation: ring 3s infinite; }
    .radar span:nth-child(2) { animation-delay: 1s; }
    .radar span:nth-child(3) { animation-delay: 2s; }
    .radar svg { width: 34px; height: 34px; fill: var(--primary); }
    @keyframes ring { 0% { transform: scale(.4); opacity: .5; } 100% { transform: scale(1.2); opacity: 0; } }

    .agent { display: flex; flex-direction: column; gap: 14px; max-width: 980px; }
    .note { padding: 18px 20px; }
    .note h2 { margin: 0 0 6px; font-size: 15px; }
    .note p { margin: 0; color: var(--text-muted); }
    .note.bad { color: var(--danger); background: var(--danger-soft); border-color: transparent; }
    .note table { border-collapse: collapse; width: 100%; font-size: 13px; }
    .note td { padding: 8px 0; border-top: 1px solid var(--border); vertical-align: top; }
    .note td:first-child { width: 200px; padding-right: 12px; }
    .note tr:first-child td { border-top: 0; }

    @media (max-width: 1100px) { .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
    @media (max-width: 760px) {
      :host { padding: 16px; }
      .live { margin-left: 0; }
      .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .workspace { grid-template-columns: 1fr; height: auto; }
      .list { max-height: 45vh; }
    }
  `,
})
export class VerifierPage {
  protected readonly store = inject(VerifyCallsStore);
  protected readonly tab = signal<Tab>('calls');
  protected readonly card = signal<AgentCard | null>(null);
  protected readonly cardError = signal<string | null>(null);
  protected readonly s = this.store.stats;

  protected readonly liveState = computed(() => {
    const c = this.store.connected();
    return c === null ? 'wait' : c ? 'on' : 'off';
  });
  protected readonly liveLabel = computed(() => ({ on: 'Live', off: 'Disconnected', wait: 'Connecting…' })[this.liveState()]);
  protected readonly lastSeen = computed(() => {
    const last = this.store.calls()[0];
    return last ? `last ${timeAgo(last.received_at, this.store.now())}` : 'none yet';
  });

  constructor() {
    fetch(`${agentApiUrl('verifier')}/card`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        this.card.set(await res.json());
      })
      .catch((err) => this.cardError.set(`Verifier agent not reachable (:8203): ${err.message ?? err}`));
  }

  protected async clear(): Promise<void> {
    if (confirm('Clear all received calls from the verifier?')) await this.store.clear();
  }
}
