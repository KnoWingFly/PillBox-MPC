const DAY_MS = 86_400_000;

/** Whole days until `iso` (rounded up, never negative): "berakhir 5 hari lagi". */
export function daysLeft(iso: string, nowMs: number = Date.now()): number {
  return Math.max(0, Math.ceil((Date.parse(iso) - nowMs) / DAY_MS));
}
