import { ChangeDetectionStrategy, Component, signal } from '@angular/core';

import { RagDocument, errorText, request, stream } from './api';
import { ProgressSteps, Step, UPLOAD_STEPS, applyEvent, failSteps, seconds } from './progress';
import { RetrievalChat } from './retrieval-chat';

interface Upload {
  name: string;
  state: 'waiting' | 'uploading' | 'done' | 'error';
  detail: string;
  steps: Step[]; // the live pipeline (POST /documents/stream)
  ms?: number;
}

/**
 * Rag-agent's own page, laid out like a chat app: a sidebar to ingest files and see what is indexed,
 * and the chat. Black on white (white on black in dark mode); the colors are scoped to this page.
 */
@Component({
  selector: 'alt-ingestion-page',
  imports: [ProgressSteps, RetrievalChat],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="app">
      <aside class="sidebar">
        <div class="brand">
          <span class="logo">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l9 5-9 5-9-5 9-5z" /><path d="M3 13l9 5 9-5" /></svg>
          </span>
          RAG
        </div>

        <button class="ingest" type="button" [disabled]="busy()" (click)="picker.click()">
          @if (busy()) {
            <span class="spinner"></span> Ingesting…
          } @else {
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
            Ingest files
          }
        </button>
        <input #picker type="file" multiple hidden [accept]="accept" (change)="ingest(picker)" />

        @if (uploads().length) {
          <div class="label">
            Uploads
            @if (!busy()) {
              <button class="icon-btn" type="button" title="Clear" (click)="uploads.set([])">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
              </button>
            }
          </div>
          @for (u of uploads(); track $index) {
            <div class="upload" [attr.data-state]="u.state">
              <div class="upload-head">
                @switch (u.state) {
                  @case ('waiting') { <span class="queued"></span> }
                  @case ('uploading') { <span class="spinner"></span> }
                  @case ('done') {
                    <svg class="ok" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7" /></svg>
                  }
                  @case ('error') {
                    <svg class="warn" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16h.01" /></svg>
                  }
                }
                <div class="name" [title]="u.name">{{ u.name }}</div>
                @if (u.ms != null) {
                  <span class="time">{{ time(u.ms) }}</span>
                }
              </div>
              <alt-progress-steps [steps]="u.steps" [compact]="true" [open]="u.state === 'uploading' || (u.state === 'error' && !!u.steps.length)" />
              @if (u.state === 'waiting' || u.state === 'done' || (u.state === 'error' && !u.steps.length)) {
                <div class="detail">{{ u.state === 'waiting' ? 'Waiting…' : u.detail }}</div>
              }
            </div>
          }
        }

        <div class="label">
          Documents
          @if (documents().length) {
            <span>{{ documents().length }}</span>
          }
        </div>
        <nav class="docs">
          @if (error(); as err) {
            <p class="note error">{{ err }}</p>
          }
          @for (d of documents(); track d.document_id) {
            <div class="doc">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /></svg>
              <span class="name" [title]="d.document_name">{{ d.document_name }}</span>
              <span class="meta" title="Chunks">{{ d.chunks }}</span>
              <button class="icon-btn danger del" type="button" [title]="'Delete ' + d.document_name" [disabled]="busy()" (click)="remove(d)">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" /></svg>
              </button>
            </div>
          } @empty {
            @if (!error()) {
              <p class="note">No documents yet. PDF (text layer), DOCX, TXT, MD and CSV are supported.</p>
            }
          }
        </nav>

        <footer class="foot">
          <span class="dot" [class.up]="online()"></span>
          {{ online() ? 'Rag agent connected' : 'Rag agent offline' }}
        </footer>
      </aside>

      <alt-retrieval-chat [documents]="documents().length" />
    </div>
  `,
  styles: `
    :host {
      --r-bg: #ffffff;
      --r-side: #f9f9f9;
      --r-text: #0d0d0d;
      --r-muted: #5d5d5d;
      --r-faint: #8f8f8f;
      --r-border: #e5e5e5;
      --r-bubble: #f4f4f4;
      --r-hover: #ececec;
      --r-accent: #0d0d0d;
      --r-on-accent: #ffffff;
      --r-danger: #d0342c;
      display: block;
      color: var(--r-text);
    }
    @media (prefers-color-scheme: dark) {
      :host {
        --r-bg: #212121;
        --r-side: #171717;
        --r-text: #ececec;
        --r-muted: #b4b4b4;
        --r-faint: #8f8f8f;
        --r-border: #383838;
        --r-bubble: #303030;
        --r-hover: #2a2a2a;
        --r-accent: #ffffff;
        --r-on-accent: #0d0d0d;
        --r-danger: #f28b82;
      }
    }
    .app { display: grid; grid-template-columns: 260px minmax(0, 1fr); height: 100vh; height: 100dvh; background: var(--r-bg); }
    .sidebar {
      display: flex; flex-direction: column; gap: 2px; min-height: 0;
      padding: 12px 10px 10px; background: var(--r-side); border-right: 1px solid var(--r-border);
    }
    .brand { display: flex; align-items: center; gap: 10px; padding: 4px 8px 14px; font-size: 15px; font-weight: 600; letter-spacing: 0.02em; }
    .logo { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 8px; background: var(--r-accent); color: var(--r-on-accent); }
    .ingest {
      display: flex; align-items: center; gap: 10px; width: 100%; padding: 9px 12px;
      font: inherit; font-weight: 500; color: var(--r-text); background: var(--r-bg);
      border: 1px solid var(--r-border); border-radius: 10px; cursor: pointer;
    }
    .ingest:hover:not(:disabled) { background: var(--r-hover); }
    .ingest:disabled { cursor: progress; color: var(--r-muted); }
    .label {
      display: flex; align-items: center; justify-content: space-between; min-height: 26px;
      padding: 14px 10px 4px; font-size: 12px; font-weight: 600; color: var(--r-faint);
    }
    .docs { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 1px; scrollbar-width: thin; scrollbar-color: var(--r-border) transparent; }
    .doc { display: flex; align-items: center; gap: 10px; padding: 7px 8px 7px 10px; border-radius: 8px; font-size: 14px; color: var(--r-text); }
    .doc:hover { background: var(--r-hover); }
    .doc > svg { flex: none; color: var(--r-muted); }
    .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .meta { font-size: 12px; color: var(--r-faint); }
    .del { opacity: 0; }
    .doc:hover .del, .del:focus-visible { opacity: 1; }
    .icon-btn {
      display: grid; place-items: center; width: 26px; height: 26px; flex: none;
      color: var(--r-muted); background: transparent; border: 0; border-radius: 6px; cursor: pointer;
    }
    .icon-btn:hover:not(:disabled) { background: var(--r-border); color: var(--r-text); }
    .icon-btn.danger:hover:not(:disabled) { color: var(--r-danger); }
    .upload {
      margin: 2px 0; padding: 8px 10px; border: 1px solid transparent; border-radius: 12px;
      transition: background-color 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease; animation: rise 0.35s ease both;
    }
    .upload[data-state='uploading'] { background: var(--r-bg); border-color: var(--r-border); box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05); }
    .upload-head { display: flex; align-items: center; gap: 10px; font-size: 13px; }
    .upload-head > svg, .upload-head > .spinner, .upload-head > .queued { flex: none; }
    .upload alt-progress-steps { transition: margin-top 0.45s ease; }
    .upload alt-progress-steps.open { margin-top: 12px; }
    .upload .detail { margin: 2px 0 0 26px; font-size: 12px; color: var(--r-faint); overflow-wrap: anywhere; animation: fade 0.3s ease both; }
    .upload[data-state='error'] .detail, .warn, .note.error { color: var(--r-danger); }
    .ok { color: var(--r-text); animation: pop 0.4s ease; }
    .time { margin-left: auto; font-size: 11.5px; color: var(--r-faint); font-variant-numeric: tabular-nums; }
    .queued { width: 16px; height: 16px; border: 1.5px dashed var(--r-faint); border-radius: 50%; }
    .doc { animation: rise 0.35s ease both; }
    @keyframes rise { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: none; } }
    @keyframes fade { from { opacity: 0; } to { opacity: 1; } }
    @keyframes pop { 0% { transform: scale(0.6); } 60% { transform: scale(1.15); } 100% { transform: scale(1); } }
    @media (prefers-reduced-motion: reduce) { .upload, .doc, .ok, .detail { animation: none; } }
    .note { margin: 4px 10px; font-size: 13px; line-height: 1.5; color: var(--r-faint); }
    .spinner {
      display: inline-block; width: 14px; height: 14px; border-radius: 50%;
      border: 2px solid var(--r-border); border-top-color: var(--r-text); animation: spin 0.8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .foot { display: flex; align-items: center; gap: 8px; margin-top: 6px; padding: 10px 10px 2px; font-size: 12px; color: var(--r-muted); border-top: 1px solid var(--r-border); }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--r-danger); }
    .dot.up { background: var(--r-text); }
    @media (max-width: 760px) {
      .app { grid-template-columns: 1fr; grid-template-rows: auto minmax(0, 1fr); }
      .sidebar { max-height: 40vh; border-right: 0; border-bottom: 1px solid var(--r-border); }
    }
  `,
})
export class IngestionPage {
  protected readonly accept = '.pdf,.docx,.txt,.md,.csv';
  protected readonly documents = signal<RagDocument[]>([]);
  protected readonly uploads = signal<Upload[]>([]);
  protected readonly busy = signal(false);
  protected readonly online = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly time = seconds;

  constructor() {
    void this.load();
  }

  /**
   * Uploads the picked files one at a time (each is chunked + embedded before the next starts), showing every step
   * live (POST /documents/stream). Each document appears in the list as soon as it is indexed.
   */
  protected async ingest(picker: HTMLInputElement): Promise<void> {
    const files = Array.from(picker.files ?? []);
    picker.value = ''; // so the same file can be picked again
    if (!files.length) return;
    this.busy.set(true);
    this.uploads.set(files.map((f) => ({ name: f.name, state: 'waiting', detail: '', steps: [] })));
    for (const [i, file] of files.entries()) {
      const body = new FormData();
      body.append('file', file);
      const started = performance.now();
      this.setUpload(i, (u) => ({ ...u, state: 'uploading' }));
      try {
        const doc = await stream<{ chunks: number }>('/documents/stream', { method: 'POST', body }, (event) =>
          this.setUpload(i, (u) => ({ ...u, steps: applyEvent(u.steps, event, UPLOAD_STEPS) })),
        );
        const ms = performance.now() - started;
        this.setUpload(i, (u) => ({ ...u, state: 'done', detail: `${doc.chunks} chunks indexed`, ms }));
        await this.load();
      } catch (err) {
        const error = errorText(err);
        const ms = performance.now() - started;
        this.setUpload(i, (u) => ({ ...u, state: 'error', detail: error, steps: failSteps(u.steps, error), ms }));
      }
    }
    this.busy.set(false);
  }

  protected async remove(doc: RagDocument): Promise<void> {
    if (!confirm(`Delete "${doc.document_name}" and its ${doc.chunks} chunks?`)) return;
    try {
      await request(`/documents/${doc.document_id}`, { method: 'DELETE' });
      await this.load();
    } catch (err) {
      this.error.set(errorText(err));
    }
  }

  private async load(): Promise<void> {
    try {
      this.documents.set(await request<RagDocument[]>('/documents'));
      this.online.set(true);
      this.error.set(null);
    } catch (err) {
      this.online.set(false);
      this.error.set(`Rag agent not reachable (:8000): ${errorText(err)}`);
    }
  }

  private setUpload(index: number, change: (u: Upload) => Upload): void {
    this.uploads.update((list) => list.map((u, i) => (i === index ? change(u) : u)));
  }
}
