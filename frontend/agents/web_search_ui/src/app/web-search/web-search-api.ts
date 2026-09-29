import { HttpClient, HttpDownloadProgressEvent, HttpEventType } from '@angular/common/http';
import { Injectable, InjectionToken, inject } from '@angular/core';
import { AgentCard, agentApiUrl } from '@altasnim/shared';
import { Observable } from 'rxjs';

import { SseMessage, SseParser } from './sse';
import { HistoryEntry, RunDetails, SearchStreamEvent, WebSearchRequest } from './web-search.models';

/**
 * Base URL of the web-search-agent's custom routes: /api/agents/web-search, proxied to :8201
 * (dev: proxy.conf.json; prod: the API gateway), so no CORS is needed.
 */
export const WEB_SEARCH_API_URL = new InjectionToken<string>('WEB_SEARCH_API_URL', {
  providedIn: 'root',
  factory: () => agentApiUrl('web_search'),
});

@Injectable()
export class WebSearchApi {
  private readonly http = inject(HttpClient);
  readonly baseUrl = inject(WEB_SEARCH_API_URL).replace(/\/$/, '');

  card(): Observable<AgentCard> {
    return this.http.get<AgentCard>(`${this.baseUrl}/card`);
  }

  /** "Retry": send another request to the output agents with the saved run - no search, no LLM. */
  retry(traceId: string): Observable<RunDetails> {
    return this.http.post<RunDetails>(`${this.baseUrl}/custom/retry`, null, { params: { trace_id: traceId } });
  }

  history(limit = 20): Observable<HistoryEntry[]> {
    return this.http.get<HistoryEntry[]>(`${this.baseUrl}/custom/history`, { params: { limit } });
  }

  /**
   * Runs the agent once via the SSE endpoint and emits each pipeline step as it happens, then the result.
   * Uses HttpClient progress events (partialText), so it works with the fetch and XHR backends.
   */
  searchStream(request: WebSearchRequest): Observable<SearchStreamEvent> {
    const body = { trace_id: crypto.randomUUID().replace(/-/g, ''), ...request };

    return new Observable<SearchStreamEvent>((subscriber) => {
      const parser = new SseParser();
      let seen = 0;
      const emit = (messages: SseMessage[]) => {
        for (const message of messages) {
          const event = toStreamEvent(message);
          if (event) {
            subscriber.next(event);
          }
        }
      };
      // partialText is cumulative; only parse what is new.
      const feed = (text: string) => {
        emit(parser.push(text.slice(seen)));
        seen = text.length;
      };

      const subscription = this.http
        .post(`${this.baseUrl}/custom/search/stream`, body, {
          observe: 'events',
          reportProgress: true,
          responseType: 'text',
          headers: { Accept: 'text/event-stream' },
        })
        .subscribe({
          next: (event) => {
            if (event.type === HttpEventType.DownloadProgress) {
              feed((event as HttpDownloadProgressEvent).partialText ?? '');
            } else if (event.type === HttpEventType.Response) {
              feed(event.body ?? '');
              emit(parser.flush());
              subscriber.complete();
            }
          },
          error: (err) => subscriber.error(err),
        });
      return () => subscription.unsubscribe();
    });
  }
}

function toStreamEvent({ event, data }: SseMessage): SearchStreamEvent | null {
  const payload = JSON.parse(data);
  switch (event) {
    case 'steps':
      return { type: 'steps', steps: payload.steps };
    case 'step':
      return { type: 'step', step: payload };
    case 'result':
      return { type: 'result', result: payload };
    case 'error':
      return { type: 'error', error: payload.error };
    default:
      return null;
  }
}
