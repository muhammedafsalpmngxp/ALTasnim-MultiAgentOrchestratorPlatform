import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { agentApiUrl } from '@altasnim/shared';

interface RagDocument {
  document_id: string;
  document_name: string;
  chunks: number;
}

interface Upload {
  name: string;
  state: 'uploading' | 'done' | 'error';
  detail: string;
}

/** Rag-agent's own page: ingest files into its Qdrant collection and see what is indexed. */
@Component({
  selector: 'alt-ingestion-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page stack">
      <div class="page-header">
        <div>
          <h1>Document ingestion</h1>
          <p class="muted">Rag agent · deployment :8000 · UI :4304 · PDF (text layer), DOCX, TXT, MD, CSV</p>
        </div>
        <button class="btn btn-primary" [disabled]="busy()" (click)="picker.click()">
          {{ busy() ? 'Ingesting…' : 'Ingest files' }}
        </button>
        <input #picker type="file" multiple hidden [accept]="accept" (change)="ingest(picker)" />
      </div>

      @if (uploads().length) {
        <div class="card stack">
          @for (u of uploads(); track $index) {
            <div class="row">
              <span class="state" [class]="u.state">{{ u.state === 'uploading' ? 'Uploading…' : u.state }}</span>
              <strong>{{ u.name }}</strong>
              <span class="muted">{{ u.detail }}</span>
            </div>
          }
        </div>
      }

      <div class="card">
        <h2>Ingested documents</h2>
        @if (error(); as err) {
          <p class="error">{{ err }}</p>
        } @else if (documents().length) {
          <table class="table">
            <thead>
              <tr><th>Document</th><th>Chunks</th><th></th></tr>
            </thead>
            <tbody>
              @for (d of documents(); track d.document_id) {
                <tr>
                  <td>{{ d.document_name }}</td>
                  <td>{{ d.chunks }}</td>
                  <td><button class="btn btn-sm btn-danger" [disabled]="busy()" (click)="remove(d)">Delete</button></td>
                </tr>
              }
            </tbody>
          </table>
        } @else {
          <p class="muted">No documents yet. Use "Ingest files" to add some.</p>
        }
      </div>
    </div>
  `,
  styles: `
    .error, .state.error { color: var(--danger); }
    .state { font-weight: 600; min-width: 90px; text-transform: capitalize; }
    .state.done { color: var(--ok); }
    .state.uploading { color: var(--warn); }
  `,
})
export class IngestionPage {
  protected readonly accept = '.pdf,.docx,.txt,.md,.csv';
  protected readonly documents = signal<RagDocument[]>([]);
  protected readonly uploads = signal<Upload[]>([]);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  constructor() {
    void this.load();
  }

  /** Uploads the picked files one at a time (each is chunked + embedded before the next starts). */
  protected async ingest(picker: HTMLInputElement): Promise<void> {
    const files = Array.from(picker.files ?? []);
    picker.value = ''; // so the same file can be picked again
    if (!files.length) return;
    this.busy.set(true);
    this.uploads.set(files.map((f) => ({ name: f.name, state: 'uploading', detail: '' })));
    for (const [i, file] of files.entries()) {
      const body = new FormData();
      body.append('file', file);
      try {
        const doc = await request<{ chunks: number }>('/documents', { method: 'POST', body });
        this.setUpload(i, 'done', `${doc.chunks} chunks indexed`);
      } catch (err) {
        this.setUpload(i, 'error', errorText(err));
      }
    }
    this.busy.set(false);
    await this.load();
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
      this.error.set(null);
    } catch (err) {
      this.error.set(`Rag agent not reachable (:8000): ${errorText(err)}`);
    }
  }

  private setUpload(index: number, state: Upload['state'], detail: string): void {
    this.uploads.update((list) => list.map((u, i) => (i === index ? { ...u, state, detail } : u)));
  }
}

async function request<T = void>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${agentApiUrl('rag')}${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
