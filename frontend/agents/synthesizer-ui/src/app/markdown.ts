/**
 * Tiny Markdown-to-HTML for the Synthesizer's short answers: paragraphs, **bold**, *italic*, `code` and
 * "-" / "1." lists. The text is HTML-escaped first, so nothing in an answer can inject markup.
 * (Kept here on purpose, so this UI adds no package to the shared frontend.)
 */

function escape(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function inline(text: string): string {
  return escape(text)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>');
}

export function renderMarkdown(text: string): string {
  const html: string[] = [];
  let list: 'ul' | 'ol' | null = null;
  const closeList = () => {
    if (list) html.push(`</${list}>`);
    list = null;
  };

  for (const block of text.replace(/\r\n/g, '\n').split(/\n{2,}/)) {
    const lines = block.split('\n').filter((l) => l.trim());
    const bullet = lines.every((l) => /^\s*[-*•]\s+/.test(l));
    const numbered = lines.every((l) => /^\s*\d+[.)]\s+/.test(l));

    if (lines.length && (bullet || numbered)) {
      const tag = bullet ? 'ul' : 'ol';
      if (list !== tag) {
        closeList();
        html.push(`<${tag}>`);
        list = tag;
      }
      for (const line of lines) html.push(`<li>${inline(line.replace(/^\s*([-*•]|\d+[.)])\s+/, ''))}</li>`);
    } else if (lines.length) {
      closeList();
      html.push(`<p>${lines.map(inline).join('<br>')}</p>`);
    }
  }
  closeList();
  return html.join('');
}

/** Removes [1]-style reference marks (older answers may still contain them). */
export function withoutCitations(text: string): string {
  return text.replace(/\s*\[\d+(?:\s*[,-]\s*\d+)*\]/g, '');
}
