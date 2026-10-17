// Schedule time helpers. A slot time is stored as minutes since midnight (Slot.timeMinutes) and
// sent to the backend as "HH:MM" 24h wall-clock time in the pillbox's timezone (devices.timezone,
// default Asia/Jakarta). The simulator stores the same "HH:MM" string. Do not change this format here.

import type { Slot, SlotId } from './types';

export const SCHEDULE_TIMEZONE_LABEL = 'WIB';
/** Asia/Jakarta is UTC+7 all year (Indonesia has no daylight saving time). */
const JAKARTA_OFFSET_MINUTES = 7 * 60;
const MINUTES_PER_DAY = 24 * 60;

export type TimeParseResult = { ok: true; minutes: number } | { ok: false; error: string };

/**
 * Input mask for typing a time: keeps digits only, max 4, and inserts ":" after the hour.
 * A first digit above 2 is read as a single-digit hour ("7" -> "07"), so "730" becomes "07:30".
 */
export function maskTimeInput(raw: string): string {
  let digits = raw.replace(/\D/g, '');
  if (digits.length > 0 && digits[0] > '2') digits = `0${digits}`;
  digits = digits.slice(0, 4);
  return digits.length > 2 ? `${digits.slice(0, 2)}:${digits.slice(2)}` : digits;
}

/** Parses "HH:MM" (24h). Error messages are shown inline to the user. */
export function parseTimeInput(text: string): TimeParseResult {
  const match = /^(\d{2}):(\d{2})$/.exec(text.trim());
  if (!match) return { ok: false, error: 'Lengkapi jam dengan format JJ:MM, contoh 07:30.' };
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours > 23) return { ok: false, error: 'Jam harus antara 00 dan 23.' };
  if (minutes > 59) return { ok: false, error: 'Menit harus antara 00 dan 59.' };
  return { ok: true, minutes: hours * 60 + minutes };
}

/**
 * Another enabled slot of the same pillbox at exactly this minute, or null. Mirrors the backend's
 * WINDOW_OVERLAP rule for zero-length windows (Backend/app/services/schedules.py find_conflicts).
 */
export function findDuplicateSlot(slots: Slot[], slotId: SlotId, minutes: number): SlotId | null {
  const other = slots.find((s) => s.id !== slotId && s.enabled && s.timeMinutes === minutes);
  return other?.id ?? null;
}

/** Every enabled slot whose time is also used by another enabled slot, mapped to that other slot. */
export function findAllDuplicates(slots: Slot[]): Map<SlotId, SlotId> {
  const conflicts = new Map<SlotId, SlotId>();
  for (const slot of slots) {
    if (!slot.enabled || slot.timeMinutes === null) continue;
    const other = findDuplicateSlot(slots, slot.id, slot.timeMinutes);
    if (other) conflicts.set(slot.id, other);
  }
  return conflicts;
}

/** Current wall-clock minutes in Asia/Jakarta, independent of the phone's timezone. */
export function jakartaMinutesNow(nowMs: number = Date.now()): number {
  const utcMinutes = Math.floor(nowMs / 60000);
  return (((utcMinutes + JAKARTA_OFFSET_MINUTES) % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY;
}

const MONTHS_ID = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];

/** "07:32" for today (WIB), otherwise "17 Okt 07:32". Independent of the phone's timezone. */
export function formatJakartaTimestamp(ms: number, nowMs: number = Date.now()): string {
  const shifted = new Date(ms + JAKARTA_OFFSET_MINUTES * 60000);
  const today = new Date(nowMs + JAKARTA_OFFSET_MINUTES * 60000);
  const clock = `${String(shifted.getUTCHours()).padStart(2, '0')}:${String(shifted.getUTCMinutes()).padStart(2, '0')}`;
  const sameDay =
    shifted.getUTCFullYear() === today.getUTCFullYear() &&
    shifted.getUTCMonth() === today.getUTCMonth() &&
    shifted.getUTCDate() === today.getUTCDate();
  return sameDay ? clock : `${shifted.getUTCDate()} ${MONTHS_ID[shifted.getUTCMonth()]} ${clock}`;
}

/** True when today's dose at `minutes` (WIB) is already in the past, so the next one is tomorrow. */
export function hasPassedToday(minutes: number, nowMs: number = Date.now()): boolean {
  return minutes <= jakartaMinutesNow(nowMs);
}

/** A Date carrying `minutes` as local wall-clock time, for the native picker. */
export function minutesToPickerDate(minutes: number): Date {
  return new Date(2000, 0, 1, Math.floor(minutes / 60), minutes % 60, 0, 0);
}

/** Reads the wall-clock time the user picked (local getters, so the phone's timezone never shifts it). */
export function pickerDateToMinutes(date: Date): number {
  return date.getHours() * 60 + date.getMinutes();
}
