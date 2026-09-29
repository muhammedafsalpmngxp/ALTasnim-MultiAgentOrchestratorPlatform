export interface SseMessage {
  event: string;
  data: string;
}

/** Incremental Server-Sent Events parser: feed it text as it arrives, get complete messages back. */
export class SseParser {
  private buffer = '';

  push(chunk: string): SseMessage[] {
    this.buffer += chunk.replace(/\r\n/g, '\n');
    const blocks = this.buffer.split('\n\n');
    this.buffer = blocks.pop() ?? ''; // last block may be incomplete
    return blocks.map(parseBlock).filter((m): m is SseMessage => m !== null);
  }

  flush(): SseMessage[] {
    const rest = this.buffer;
    this.buffer = '';
    const message = rest.trim() ? parseBlock(rest) : null;
    return message ? [message] : [];
  }
}

function parseBlock(block: string): SseMessage | null {
  let event = 'message';
  const data: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      data.push(line.slice(5).replace(/^ /, ''));
    }
  }
  return data.length ? { event, data: data.join('\n') } : null;
}
