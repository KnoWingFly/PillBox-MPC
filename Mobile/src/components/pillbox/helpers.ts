import { Strings } from '@/constants/strings';
import * as api from '@root/lib/api';
import type { DoseStatus, TodayDose } from '@root/lib/insights';
import type { NotificationFilter } from '@root/lib/notifications';
import { scheduleMinutesNow, scheduleParts } from '@root/lib/schedule-time';
import type { AppNotification, DeviceStatus, NotificationType, Slot, SlotId, ToleranceMinutes } from '@root/lib/types';

import type { IconName, Tone } from './ui';

/** Battery at or below this percentage is flagged as low. */
export const LOW_BATTERY_PERCENT = 20;
/** An online pillbox that has not synced for this long is shown as "belum sinkron". */
export const STALE_SYNC_MS = 10 * 60 * 1000;
/** Used when an empty slot gets its first time: Pagi, Siang, Sore, Malam. */
export const COLUMN_DEFAULT_TIMES = [7 * 60, 12 * 60, 18 * 60, 21 * 60] as const;
const COLUMN_ICONS: IconName[] = ['sunny-outline', 'sunny', 'partly-sunny-outline', 'moon-outline'];
export const COLUMNS: { label: string; icon: IconName }[] = Strings.shell.periods.map((label, i) => ({
  label,
  icon: COLUMN_ICONS[i],
}));
export const ROWS = [
  { key: 'A', label: Strings.shell.rows.A },
  { key: 'B', label: Strings.shell.rows.B },
] as const;
export const TOLERANCE_OPTIONS: { value: ToleranceMinutes; label: string }[] = [
  { value: 15, label: '15 menit' },
  { value: 30, label: '30 menit' },
  { value: 45, label: '45 menit' },
  { value: 60, label: '1 jam' },
];

export const EMPTY_TEXT: Record<NotificationFilter, { title: string; text: string }> = {
  all: { title: 'Belum ada notifikasi', text: 'Kejadian dari Pillbox akan muncul di sini.' },
  on_time: { title: 'Belum ada yang tepat waktu', text: 'Obat yang diminum sesuai jadwal akan muncul di sini.' },
  issues: { title: 'Semua aman', text: 'Tidak ada dosis terlambat atau terlewat.' },
  system: { title: 'Belum ada notifikasi sistem', text: 'Info koneksi dan baterai Pillbox akan muncul di sini.' },
};

export type ToastTone = 'success' | 'info' | 'warning' | 'error';

type NotificationLook = { label: string; tone: Tone; icon: IconName; toast: ToastTone };

const NOTIFICATION_LOOK: Record<NotificationType, NotificationLook> = {
  on_time: { label: 'Tepat Waktu', tone: 'ontime', icon: 'checkmark-circle', toast: 'success' },
  late: { label: 'Terlambat', tone: 'late', icon: 'time', toast: 'warning' },
  missed: { label: 'Terlewat', tone: 'missed', icon: 'alert-circle', toast: 'error' },
  system: { label: 'Sistem', tone: 'info', icon: 'information-circle', toast: 'info' },
};

/** Critical system alerts (e.g. compartment opened outside its schedule) stay under "Sistem" but look urgent. */
const CRITICAL_SYSTEM_LOOK: NotificationLook = { label: 'Peringatan Sistem', tone: 'missed', icon: 'warning', toast: 'error' };

export function notificationLook(n: AppNotification): NotificationLook {
  return n.type === 'system' && n.severity === 'critical' ? CRITICAL_SYSTEM_LOOK : NOTIFICATION_LOOK[n.type];
}

export function formatRelative(timestamp: number, now: number): string {
  const minutes = Math.floor(Math.max(0, now - timestamp) / 60000);
  if (minutes < 1) return 'Baru saja';
  if (minutes < 60) return `${minutes} menit lalu`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} jam lalu`;
  return `${Math.floor(hours / 24)} hari lalu`;
}

export function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} menit`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h} jam` : `${h} jam ${m} menit`;
}

export function isSlotActive(slot: Slot | undefined): boolean {
  return !!slot && slot.enabled && slot.timeMinutes !== null;
}

function slotsEqual(a: Slot, b: Slot): boolean {
  return (
    a.timeMinutes === b.timeMinutes &&
    a.enabled === b.enabled &&
    a.toleranceMinutes === b.toleranceMinutes &&
    a.stock === b.stock
  );
}

export function isSlotChanged(slot: Slot, saved: Slot[]): boolean {
  const original = saved.find((s) => s.id === slot.id);
  return !original || !slotsEqual(original, slot);
}

export function isDraftDirty(draft: Slot[], saved: Slot[]): boolean {
  return draft.some((slot) => isSlotChanged(slot, saved));
}

export function columnIndex(id: SlotId): number {
  return Number(id[1]) - 1;
}

export function slotTitle(id: SlotId): string {
  return `${api.getSlotColumnLabel(id)}, ${api.getSlotRowLabel(id)}`;
}

export type DeviceLook = { tone: Tone; label: string; detail: string; icon: IconName };

export function deviceLook(device: DeviceStatus, now: number): DeviceLook {
  if (!device.online) {
    return {
      tone: 'missed',
      label: 'Terputus',
      detail: 'Pillbox tidak terhubung. Jadwal baru dikirim saat tersambung lagi.',
      icon: 'cloud-offline',
    };
  }
  if (now - device.lastSyncedAt > STALE_SYNC_MS) {
    return {
      tone: 'late',
      label: 'Belum sinkron',
      detail: 'Pillbox terhubung, tetapi belum sinkron lebih dari 10 menit.',
      icon: 'sync',
    };
  }
  return { tone: 'ontime', label: 'Terhubung', detail: 'Pillbox terhubung dan jadwal tersinkron.', icon: 'checkmark-circle' };
}

/** "Now" on the pillbox clock (epoch ms); the phone clock when the pillbox reports none. */
export function pillboxNow(device: DeviceStatus | null, nowMs: number): number {
  const clock = device?.clock;
  return clock ? clock.deviceTimeMs + (nowMs - clock.receivedAt) * clock.speed : nowMs;
}

/** "Simulasi 60x · 3 jam 5 menit lebih cepat" when the pillbox clock is not on real time; null otherwise. */
export function pillboxClockNote(device: DeviceStatus | null, nowMs: number): string | null {
  const clock = device?.clock;
  if (!clock) return null;
  const parts: string[] = [];
  if (clock.speed !== 1) parts.push(`Simulasi ${clock.speed}x`);
  const offset = Math.round((pillboxNow(device, nowMs) - nowMs) / 60000);
  if (Math.abs(offset) >= 2) {
    const hours = Math.floor(Math.abs(offset) / 60);
    const minutes = Math.abs(offset) % 60;
    const amount = [hours ? `${hours} jam` : '', minutes ? `${minutes} menit` : ''].filter(Boolean).join(' ');
    parts.push(`${amount} ${offset > 0 ? 'lebih cepat' : 'lebih lambat'}`);
  }
  return parts.length ? parts.join(' · ') : null;
}

/** The next active dose (pillbox clock): today if still ahead, otherwise the first one tomorrow. */
export function nextDose(slots: Slot[], nowMs: number): { slot: Slot; inMinutes: number; tomorrow: boolean } | null {
  const active = slots.filter(isSlotActive).sort((a, b) => (a.timeMinutes ?? 0) - (b.timeMinutes ?? 0));
  if (active.length === 0) return null;
  const now = scheduleMinutesNow(nowMs);
  const today = active.find((s) => (s.timeMinutes ?? 0) > now);
  if (today) return { slot: today, inMinutes: (today.timeMinutes ?? 0) - now, tomorrow: false };
  const first = active[0];
  return { slot: first, inMinutes: 24 * 60 - now + (first.timeMinutes ?? 0), tomorrow: true };
}

/** "Sabtu, 17 Oktober" on the pillbox clock, independent of the phone's timezone. */
export function formatPillboxDate(nowMs: number): string {
  const p = scheduleParts(nowMs);
  const c = Strings.calendar;
  return c.dayDate(c.days[p.weekday], p.day, c.months[p.month - 1]);
}

/** Adherence at or above these percentages is "Sangat Baik" / "Baik"; below is "Perlu Perhatian". */
export const ADHERENCE_GREAT_PERCENT = 90;
export const ADHERENCE_GOOD_PERCENT = 75;

export function adherenceBand(percent: number | null): { label: string; tone: Tone } {
  const bands = Strings.home.adherenceBands;
  if (percent === null) return { label: bands.none, tone: 'neutral' };
  if (percent >= ADHERENCE_GREAT_PERCENT) return { label: bands.great, tone: 'ontime' };
  if (percent >= ADHERENCE_GOOD_PERCENT) return { label: bands.good, tone: 'late' };
  return { label: bands.low, tone: 'missed' };
}

const DOSE_TONE: Record<DoseStatus, Tone> = {
  PENDING: 'primary',
  TAKEN_ON_TIME: 'ontime',
  TAKEN_LATE: 'late',
  MISSED: 'missed',
};

export function doseLook(dose: Pick<TodayDose, 'status' | 'delayMinutes'>): { label: string; tone: Tone } {
  const s = Strings.home.status;
  const label = dose.status === 'TAKEN_LATE' ? s.TAKEN_LATE(dose.delayMinutes) : s[dose.status];
  return { label, tone: DOSE_TONE[dose.status] };
}

/** Whole years between a "YYYY-MM-DD" birth date and `nowMs` (pillbox calendar); null when unknown. */
export function ageInYears(birthDate: string | null, nowMs: number): number | null {
  if (!birthDate) return null;
  const [y, m, d] = birthDate.split('-').map(Number);
  const today = scheduleParts(nowMs);
  const beforeBirthday = today.month < m || (today.month === m && today.day < d);
  return today.year - y - (beforeBirthday ? 1 : 0);
}

/** "15:06:26" on the pillbox clock. */
export function formatPillboxClock(ms: number): string {
  const p = scheduleParts(ms);
  return [p.hour, p.minute, p.second].map((n) => String(n).padStart(2, '0')).join(':');
}

/** "86%", or "—" when the pillbox has not reported its battery. */
export function formatBattery(percent: number | null): string {
  return percent === null ? Strings.common.noValue : Strings.shell.percent(percent);
}

export function isLowBattery(percent: number | null): boolean {
  return percent !== null && percent <= LOW_BATTERY_PERCENT;
}

/** "15% · Lemah" when low, "86%" otherwise, "—" when unknown. */
export function batteryText(percent: number | null): string {
  return percent !== null && isLowBattery(percent) ? Strings.device.batteryLow(percent) : formatBattery(percent);
}

/** First word of a name, for greetings ("Halo, Arya"). */
export function firstName(name: string | null | undefined): string {
  return name?.trim().split(/\s+/)[0] || Strings.shell.caregiverFallback;
}
