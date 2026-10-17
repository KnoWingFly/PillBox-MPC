import * as api from '@root/lib/api';
import type { NotificationFilter } from '@root/lib/notifications';
import { jakartaMinutesNow } from '@root/lib/schedule-time';
import type { AppNotification, DeviceStatus, NotificationType, Slot, SlotId, ToleranceMinutes } from '@root/lib/types';

import type { IconName, Tone } from './ui';

/** Battery at or below this percentage is flagged as low. */
export const LOW_BATTERY_PERCENT = 20;
/** An online pillbox that has not synced for this long is shown as "belum sinkron". */
export const STALE_SYNC_MS = 10 * 60 * 1000;
/** Used when an empty slot gets its first time: Pagi, Siang, Sore, Malam. */
export const COLUMN_DEFAULT_TIMES = [7 * 60, 12 * 60, 18 * 60, 21 * 60] as const;
export const COLUMNS: { label: string; icon: IconName }[] = [
  { label: 'Pagi', icon: 'sunny-outline' },
  { label: 'Siang', icon: 'sunny' },
  { label: 'Sore', icon: 'partly-sunny-outline' },
  { label: 'Malam', icon: 'moon-outline' },
];
export const ROWS = [
  { key: 'A', label: 'Sebelum Makan' },
  { key: 'B', label: 'Sesudah Makan' },
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

/** The next active dose (WIB): today if still ahead, otherwise the first one tomorrow. */
export function nextDose(slots: Slot[], nowMs: number): { slot: Slot; inMinutes: number; tomorrow: boolean } | null {
  const active = slots.filter(isSlotActive).sort((a, b) => (a.timeMinutes ?? 0) - (b.timeMinutes ?? 0));
  if (active.length === 0) return null;
  const now = jakartaMinutesNow(nowMs);
  const today = active.find((s) => (s.timeMinutes ?? 0) > now);
  if (today) return { slot: today, inMinutes: (today.timeMinutes ?? 0) - now, tomorrow: false };
  const first = active[0];
  return { slot: first, inMinutes: 24 * 60 - now + (first.timeMinutes ?? 0), tomorrow: true };
}

const DAYS_ID = ['Minggu', 'Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu'];
const MONTHS_ID = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];

/** "Sabtu, 17 Oktober" in WIB, independent of the phone's timezone. */
export function formatJakartaDate(nowMs: number): string {
  const d = new Date(nowMs + 7 * 60 * 60000);
  return `${DAYS_ID[d.getUTCDay()]}, ${d.getUTCDate()} ${MONTHS_ID[d.getUTCMonth()]}`;
}

export function greeting(nowMs: number): string {
  const hour = Math.floor(jakartaMinutesNow(nowMs) / 60);
  if (hour < 11) return 'Selamat pagi';
  if (hour < 15) return 'Selamat siang';
  if (hour < 18) return 'Selamat sore';
  return 'Selamat malam';
}
