/**
 * Safe date formatting utilities.
 * All functions return "—" for null / undefined / zero / invalid inputs.
 */

const LOCALE = 'zh-CN';
const FALLBACK = '—';

/** Coerce any date-like value to a valid Date, or null. */
function toDate(val: unknown): Date | null {
  if (val == null || val === '' || val === 0 || val === '0') return null;
  const d = val instanceof Date ? val : new Date(val as string | number);
  return isNaN(d.getTime()) ? null : d;
}

/** HH:MM:SS  e.g. "14:05:30" */
export function fmtTime(val: unknown): string {
  const d = toDate(val);
  if (!d) return FALLBACK;
  return d.toLocaleTimeString(LOCALE);
}

/** YYYY/MM/DD HH:MM:SS  e.g. "2025/5/1 14:05:30" */
export function fmtDateTime(val: unknown): string {
  const d = toDate(val);
  if (!d) return FALLBACK;
  return d.toLocaleString(LOCALE);
}

/** YYYY/MM/DD  e.g. "2025/5/1" */
export function fmtDate(val: unknown): string {
  const d = toDate(val);
  if (!d) return FALLBACK;
  return d.toLocaleDateString(LOCALE);
}

/**
 * Unix epoch in SECONDS → formatted datetime.
 * Multiplies by 1000 for you; returns "—" if val is falsy/zero.
 */
export function fmtUnixTime(val: unknown): string {
  if (!val) return FALLBACK;
  return fmtTime(Number(val) * 1000);
}

export function fmtUnixDateTime(val: unknown): string {
  if (!val) return FALLBACK;
  return fmtDateTime(Number(val) * 1000);
}
