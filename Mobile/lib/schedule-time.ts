// Schedule time helpers. A slot time is stored as minutes since midnight (Slot.timeMinutes) and
// sent to the backend as "HH:MM" 24h wall-clock time in the pillbox's timezone (devices.timezone,
// AppConfig.fallbackTimezone until the pillbox reports one). The simulator stores the same "HH:MM"
// string. Do not change this format here.

import { AppConfig } from '@/config';
import { Strings } from '@/constants/strings';

import type { Slot, SlotId } from './types';

const MINUTES_PER_DAY = 24 * 60;
const MINUTES_PER_HOUR = 60;

// --- pillbox timezone ---------------------------------------------------------------
// Doses are due by the pillbox's wall clock, so "today", "now" and every shown time use its IANA
// timezone, never the phone's. lib/insights.ts sets it when it reads the device; switching pillbox
// resets it (lib/api.ts setActivePillbox).

let scheduleTz: string = AppConfig.fallbackTimezone;

const formatters = new Map<string, Intl.DateTimeFormat>();

/** Cached (creating an Intl formatter is slow); null when the platform does not know `tz`. */
function formatterFor(tz: string): Intl.DateTimeFormat | null {
  const cached = formatters.get(tz);
  if (cached) return cached;
  try {
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      hourCycle: 'h23',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric',
      weekday: 'short',
    });
    formatters.set(tz, formatter);
    return formatter;
  } catch {
    return null;
  }
}

/** Uses the pillbox's timezone from now on; an unknown or empty one falls back to AppConfig. */
export function setScheduleTimezone(tz: string | null | undefined): void {
  scheduleTz = tz && formatterFor(tz) ? tz : AppConfig.fallbackTimezone;
}

export function resetScheduleTimezone(): void {
  scheduleTz = AppConfig.fallbackTimezone;
}

export function scheduleTimezone(): string {
  return scheduleTz;
}

/** "WIB" / "WITA" / "WIT" for Indonesian zones, otherwise the platform's short name (e.g. "GMT+8"). */
export function timezoneLabel(tz: string = scheduleTz): string {
  const known = Strings.timezones[tz];
  if (known) return known;
  try {
    const part = new Intl.DateTimeFormat('id-ID', { timeZone: tz, timeZoneName: 'short' })
      .formatToParts(0)
      .find((p) => p.type === 'timeZoneName');
    return part?.value ?? tz;
  } catch {
    return tz;
  }
}

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

export type ZonedParts = {
  year: number;
  /** 1-12 */
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
  /** 0 = Sunday, like Date.getDay(). */
  weekday: number;
};

/** Calendar fields of `ms` on the pillbox's wall clock. */
export function scheduleParts(ms: number, tz: string = scheduleTz): ZonedParts {
  const formatter = formatterFor(tz) ?? formatterFor(AppConfig.fallbackTimezone);
  if (!formatter) {
    const d = new Date(ms); // no Intl timezone support at all: UTC is the least surprising
    return {
      year: d.getUTCFullYear(),
      month: d.getUTCMonth() + 1,
      day: d.getUTCDate(),
      hour: d.getUTCHours(),
      minute: d.getUTCMinutes(),
      second: d.getUTCSeconds(),
      weekday: d.getUTCDay(),
    };
  }
  const out: Record<string, string> = {};
  for (const part of formatter.formatToParts(ms)) out[part.type] = part.value;
  return {
    year: Number(out.year),
    month: Number(out.month),
    day: Number(out.day),
    hour: Number(out.hour),
    minute: Number(out.minute),
    second: Number(out.second),
    weekday: WEEKDAYS.indexOf(out.weekday),
  };
}

const pad2 = (n: number) => String(n).padStart(2, '0');

/** "YYYY-MM-DD" of `ms` on the pillbox's wall clock. */
export function scheduleDateKey(ms: number): string {
  const p = scheduleParts(ms);
  return `${p.year}-${pad2(p.month)}-${pad2(p.day)}`;
}

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
  if (!match) return { ok: false, error: Strings.timeInput.format };
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours >= MINUTES_PER_DAY / MINUTES_PER_HOUR) return { ok: false, error: Strings.timeInput.hourRange };
  if (minutes >= MINUTES_PER_HOUR) return { ok: false, error: Strings.timeInput.minuteRange };
  return { ok: true, minutes: hours * 60 + minutes };
}

/** Why two enabled slots cannot both ring: the same minute, or one's dose window (time +
 * tolerance, while it may stay popped up) running into the other's. The pillbox opens one chamber at
 * a time, so the later dose would wait in a queue and could be missed. `gapMinutes` is what the
 * earlier slot needs before the next may start (its tolerance). */
export type SlotConflict = { other: SlotId; kind: 'same_time' | 'too_close'; gapMinutes: number };

/**
 * The first enabled slot that conflicts with `slotId` at `minutes` with `toleranceMinutes`, or null.
 * Mirrors the backend rule (Backend/app/services/schedules.py find_conflicts, SCHEDULE_TOO_CLOSE),
 * including dose windows that run past midnight.
 */
export function findSlotConflict(
  slots: Slot[],
  slotId: SlotId,
  minutes: number,
  toleranceMinutes: number,
): SlotConflict | null {
  for (const other of slots) {
    if (other.id === slotId || !other.enabled || other.timeMinutes === null) continue;
    if (other.timeMinutes === minutes) return { other: other.id, kind: 'same_time', gapMinutes: 0 };
    for (const shift of [-MINUTES_PER_DAY, 0, MINUTES_PER_DAY]) {
      const otherStart = other.timeMinutes + shift;
      const overlaps = minutes < otherStart + other.toleranceMinutes && otherStart < minutes + toleranceMinutes;
      if (overlaps) {
        const gapMinutes = minutes < otherStart ? toleranceMinutes : other.toleranceMinutes;
        return { other: other.id, kind: 'too_close', gapMinutes };
      }
    }
  }
  return null;
}

/** Every enabled slot that conflicts with another enabled slot, with the conflict. */
export function findAllConflicts(slots: Slot[]): Map<SlotId, SlotConflict> {
  const conflicts = new Map<SlotId, SlotConflict>();
  for (const slot of slots) {
    if (!slot.enabled || slot.timeMinutes === null) continue;
    const conflict = findSlotConflict(slots, slot.id, slot.timeMinutes, slot.toleranceMinutes);
    if (conflict) conflicts.set(slot.id, conflict);
  }
  return conflicts;
}

/** Current wall-clock minutes on the pillbox, independent of the phone's timezone. */
export function scheduleMinutesNow(nowMs: number = Date.now()): number {
  const p = scheduleParts(nowMs);
  return (p.hour * MINUTES_PER_HOUR + p.minute) % MINUTES_PER_DAY;
}

/** "07:32" for today (pillbox clock), otherwise "17 Okt 07:32". Independent of the phone's timezone. */
export function formatScheduleTimestamp(ms: number, nowMs: number = Date.now()): string {
  const at = scheduleParts(ms);
  const today = scheduleParts(nowMs);
  const clock = `${pad2(at.hour)}:${pad2(at.minute)}`;
  const sameDay = at.year === today.year && at.month === today.month && at.day === today.day;
  return sameDay ? clock : `${at.day} ${Strings.calendar.monthsShort[at.month - 1]} ${clock}`;
}

/** True when today's dose at `minutes` (pillbox clock) is already in the past, so the next one is tomorrow. */
export function hasPassedToday(minutes: number, nowMs: number = Date.now()): boolean {
  return minutes <= scheduleMinutesNow(nowMs);
}

/** A Date carrying `minutes` as local wall-clock time, for the native picker. */
export function minutesToPickerDate(minutes: number): Date {
  return new Date(2000, 0, 1, Math.floor(minutes / 60), minutes % 60, 0, 0);
}

/** Reads the wall-clock time the user picked (local getters, so the phone's timezone never shifts it). */
export function pickerDateToMinutes(date: Date): number {
  return date.getHours() * 60 + date.getMinutes();
}
