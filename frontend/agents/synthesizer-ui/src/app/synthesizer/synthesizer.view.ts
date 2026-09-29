/**
 * Turns any data an agent sends (text, objects, lists of chunks, nested results) into something readable.
 */

export interface DataItem {
  title: string | null;
  text: string;
  url: string | null;
  /** e.g. en.wikipedia.org */
  site: string | null;
}

export interface InputView {
  name: string;
  status: string | null;
  /** One main text: a string value, or an object's summary. Left out when it only repeats the list. */
  text: string;
  /** List entries: chunks, findings, results, ... */
  items: DataItem[];
  /** Everything, as it was received */
  raw: string;
}

const TEXT_KEYS = ['summary', 'text', 'content', 'answer', 'snippet', 'chunk', 'body', 'message', 'objective', 'title'];
const URL_KEYS = ['url', 'link', 'source', 'href'];
const LIST_KEYS = ['chunks', 'findings', 'results', 'documents', 'docs', 'items', 'data', 'hits', 'sources'];

function isObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function firstString(obj: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = obj[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}

/** A text summary longer than this, next to a list, is just the list again: show the list only. */
const MAX_TEXT_WITH_LIST = 200;

function site(url: string | null): string | null {
  try {
    return url ? new URL(url).hostname.replace(/^www\./, '') : null;
  } catch {
    return null;
  }
}

function toItem(value: unknown): DataItem {
  if (typeof value === 'string') {
    const url = /^https?:\/\//.test(value) ? value : null;
    return { title: null, text: url ? '' : value, url, site: site(url) };
  }
  if (isObject(value)) {
    const url = firstString(value, URL_KEYS);
    const title = firstString(value, ['title', 'name']);
    const text = firstString(value, ['text', 'content', 'snippet', 'chunk', 'summary', 'body']) ?? '';
    return { title, text: text || (title || url ? '' : JSON.stringify(value)), url, site: site(url) };
  }
  return { title: null, text: JSON.stringify(value), url: null, site: null };
}

export function toInputView(name: string, value: unknown): InputView {
  const raw = typeof value === 'string' ? value : JSON.stringify(value, null, 2);

  if (Array.isArray(value)) {
    return { name, status: null, text: '', items: value.map(toItem), raw };
  }
  if (isObject(value)) {
    const list = LIST_KEYS.map((k) => value[k]).find((v) => Array.isArray(v) && v.length) as unknown[] | undefined;
    const items = list ? list.map(toItem) : [];
    const text = firstString(value, TEXT_KEYS.filter((k) => k !== 'title')) ?? '';
    return {
      name,
      status: typeof value['status'] === 'string' ? value['status'] : null,
      text: items.length && text.length > MAX_TEXT_WITH_LIST ? '' : text,
      items,
      raw,
    };
  }
  return { name, status: null, text: value == null ? '' : String(value), items: [], raw };
}
