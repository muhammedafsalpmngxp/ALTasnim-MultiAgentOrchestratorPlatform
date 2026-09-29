/** Seconds with two decimals under 10 s ("1.24 s"), one above ("12.3 s"). */
export function formatSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return '';
  }
  return `${seconds.toFixed(seconds < 10 ? 2 : 1)} s`;
}

/** Formats ISO / RFC 2822 dates; returns the raw value if it cannot be parsed. */
export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}
