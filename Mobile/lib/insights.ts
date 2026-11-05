// Extra data for the redesigned dashboard tabs (Beranda, PillBox, Pengaturan): today's doses,
// missed doses per weekday, the elderly profile, the pillbox clock and notification preferences.
// Backend mode calls the FastAPI routes below; mock mode derives the same shapes from the mock data.

import { AppConfig } from '@/config';

import {
  activePillboxDeviceId,
  activePillboxElderlyId,
  backendRequest,
  BackendError,
  getSchedules,
  setMockNotifications,
  getMockNotifications,
  USE_MOCK,
} from './api';
import { jakartaMinutesNow } from './schedule-time';
import { SLOT_IDS, type SlotId } from './types';

const JAKARTA_OFFSET_MS = 7 * 3600_000;
const DAY_MS = 86_400_000;
/** Days in the missed-dose chart (Monday to Sunday). */
export const WEEK_DAYS = 7;

/** Backend JournalStatus (API list): PENDING -> TAKEN_ON_TIME | TAKEN_LATE | MISSED. */
export type DoseStatus = 'PENDING' | 'TAKEN_ON_TIME' | 'TAKEN_LATE' | 'MISSED';

export interface TodayDose {
  key: string;
  slotId: SlotId;
  deviceId: string | null;
  /** "HH:MM" in the device timezone. */
  scheduledTime: string;
  status: DoseStatus;
  delayMinutes: number | null;
}

export interface WeekMissed {
  /** Missed doses Monday..Sunday of the week that contains `today`. */
  days: { date: string; missed: number }[];
  /** Index of today in `days`. */
  todayIndex: number;
  /** Missed doses in the whole previous week; null when unknown. */
  previousTotal: number | null;
}

export interface ElderlyDetail {
  id: string;
  fullName: string;
  birthDate: string | null;
  contactPhone: string | null;
  caregiverCount: number;
}

export interface DeviceClock {
  isAccurate: boolean | null;
  autoSyncTimezone: boolean;
  timezone: string;
}

/** Backend NotificationPreferencesIO, wire shape (snake_case), sent back whole on PUT. */
export interface NotificationPreferences {
  channels: { push: boolean; whatsapp: boolean };
  whatsapp_number: string | null;
  notify_on_missed: boolean;
  notify_on_taken: boolean;
  notify_on_device_offline: boolean;
  device_offline_after_minutes: number;
  notify_on_low_battery: boolean;
}

export type PreferenceToggle = 'notify_on_missed' | 'notify_on_taken' | 'notify_on_device_offline' | 'notify_on_low_battery';

type BackendDoseCard = {
  dose_log_id: string | null;
  device_id: string;
  slot_number: number;
  scheduled_time: string;
  status: DoseStatus;
  delay_minutes: number | null;
};
type BackendDay = { doses: BackendDoseCard[] };
type BackendCalendar = { days: { date: string; missed: number }[] };
type BackendElderly = {
  id: string;
  full_name: string;
  birth_date: string | null;
  contact_phone: string | null;
  caregiver_count: number;
};
type BackendClock = { is_accurate: boolean | null; auto_sync_timezone: boolean };
type BackendDeviceDetail = { timezone: string; auto_sync_timezone: boolean };

/** "YYYY-MM-DD" of `ms` in WIB (the schedule timezone, see lib/schedule-time.ts). */
function jakartaDay(ms: number): string {
  return new Date(ms + JAKARTA_OFFSET_MS).toISOString().slice(0, 10);
}

function elderly(): string {
  const id = activePillboxElderlyId();
  if (!id) throw new BackendError(404, 'NO_DEVICE', 'No pillbox selected.');
  return id;
}

function device(): string {
  const id = activePillboxDeviceId();
  if (!id) throw new BackendError(404, 'NO_DEVICE', 'No pillbox selected.');
  return id;
}

function formatHHmm(minutes: number): string {
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
}

/**
 * Today's doses of the active pillbox, in time order. `dayMs` is "now" on the pillbox clock.
 * Backend: GET /elderly/{id}/journal/{date}, filtered to the active device.
 */
export async function getTodayDoses(dayMs: number): Promise<TodayDose[]> {
  if (!USE_MOCK) {
    const res = await backendRequest<BackendDay>(`/elderly/${elderly()}/journal/${jakartaDay(dayMs)}`);
    const deviceId = activePillboxDeviceId();
    return res.doses
      .filter((d) => !deviceId || d.device_id === deviceId)
      .map((d) => ({
        key: d.dose_log_id ?? `${d.device_id}-${d.slot_number}`,
        slotId: SLOT_IDS[d.slot_number - 1],
        deviceId: d.device_id,
        scheduledTime: d.scheduled_time.slice(0, 5),
        status: d.status,
        delayMinutes: d.delay_minutes,
      }))
      .sort((a, b) => a.scheduledTime.localeCompare(b.scheduledTime));
  }
  // Mock: active slots, already-passed ones counted as taken on time.
  const now = jakartaMinutesNow(dayMs);
  const slots = await getSchedules();
  return slots
    .filter((s) => s.enabled && s.timeMinutes !== null)
    .sort((a, b) => (a.timeMinutes ?? 0) - (b.timeMinutes ?? 0))
    .map((s) => ({
      key: s.id,
      slotId: s.id,
      deviceId: null,
      scheduledTime: formatHHmm(s.timeMinutes ?? 0),
      status: (s.timeMinutes ?? 0) <= now ? 'TAKEN_ON_TIME' : 'PENDING',
      delayMinutes: (s.timeMinutes ?? 0) <= now ? 0 : null,
    }));
}

/**
 * Missed doses per day for this week (Mon-Sun) and the previous week's total, per elderly profile.
 * Backend: GET /elderly/{id}/journal/calendar?month=YYYY-MM for each month the two weeks touch.
 */
export async function getWeekMissed(dayMs: number): Promise<WeekMissed> {
  const today = new Date(dayMs + JAKARTA_OFFSET_MS);
  const todayIndex = (today.getUTCDay() + WEEK_DAYS - 1) % WEEK_DAYS; // Monday = 0
  const monday = dayMs - todayIndex * DAY_MS;
  const dates = Array.from({ length: WEEK_DAYS }, (_, i) => jakartaDay(monday + i * DAY_MS));
  const previous = Array.from({ length: WEEK_DAYS }, (_, i) => jakartaDay(monday - (WEEK_DAYS - i) * DAY_MS));
  if (USE_MOCK) {
    return { days: dates.map((date) => ({ date, missed: 0 })), todayIndex, previousTotal: null };
  }
  const months = [...new Set([...previous, ...dates].map((d) => d.slice(0, 7)))];
  const id = elderly();
  const pages = await Promise.all(months.map((m) => backendRequest<BackendCalendar>(`/elderly/${id}/journal/calendar?month=${m}`)));
  const missedByDate = new Map(pages.flatMap((p) => p.days.map((d) => [d.date, d.missed] as const)));
  return {
    days: dates.map((date) => ({ date, missed: missedByDate.get(date) ?? 0 })),
    todayIndex,
    previousTotal: previous.reduce((sum, d) => sum + (missedByDate.get(d) ?? 0), 0),
  };
}

/** The active pillbox's elderly profile; null in mock mode. Backend: GET /elderly/{id}. */
export async function getElderlyDetail(): Promise<ElderlyDetail | null> {
  if (USE_MOCK) return null;
  const e = await backendRequest<BackendElderly>(`/elderly/${elderly()}`);
  return {
    id: e.id,
    fullName: e.full_name,
    birthDate: e.birth_date,
    contactPhone: e.contact_phone,
    caregiverCount: e.caregiver_count,
  };
}

/** Clock accuracy and timezone of the active pillbox. Backend: GET /devices/{id}/clock and /devices/{id}. */
export async function getDeviceClock(): Promise<DeviceClock> {
  if (USE_MOCK) return { isAccurate: true, autoSyncTimezone: true, timezone: AppConfig.fallbackTimezone };
  const id = device();
  const [clock, detail] = await Promise.all([
    backendRequest<BackendClock>(`/devices/${id}/clock`),
    backendRequest<BackendDeviceDetail>(`/devices/${id}`),
  ]);
  return { isAccurate: clock.is_accurate, autoSyncTimezone: clock.auto_sync_timezone, timezone: detail.timezone };
}

/** Sets the pillbox clock from the server. Backend: POST /devices/{id}/clock/calibrate (device PIN). */
export async function calibrateDeviceClock(pin: string): Promise<void> {
  if (USE_MOCK) return;
  await backendRequest(`/devices/${device()}/clock/calibrate`, 'POST', { device_pin: pin });
}

/** "Sinkron otomatis zona waktu". Backend: PUT /devices/{id} (OWNER / ADMIN). */
export async function setAutoSyncTimezone(enabled: boolean): Promise<void> {
  if (USE_MOCK) return;
  await backendRequest(`/devices/${device()}`, 'PUT', { auto_sync_timezone: enabled });
}

const DEFAULT_PREFERENCES: NotificationPreferences = {
  channels: { push: true, whatsapp: false },
  whatsapp_number: null,
  notify_on_missed: true,
  notify_on_taken: true,
  notify_on_device_offline: true,
  device_offline_after_minutes: 10,
  notify_on_low_battery: true,
};
let mockPreferences = DEFAULT_PREFERENCES;

/** Backend: GET /elderly/{id}/notification-preferences. */
export async function getNotificationPreferences(): Promise<NotificationPreferences> {
  if (USE_MOCK) return mockPreferences;
  return backendRequest<NotificationPreferences>(`/elderly/${elderly()}/notification-preferences`);
}

/** Backend: PUT /elderly/{id}/notification-preferences (the whole object). */
export async function saveNotificationPreferences(prefs: NotificationPreferences): Promise<NotificationPreferences> {
  if (USE_MOCK) {
    mockPreferences = prefs;
    return prefs;
  }
  return backendRequest<NotificationPreferences>(`/elderly/${elderly()}/notification-preferences`, 'PUT', prefs);
}

/** "Tandai dibaca": every notification of this caregiver. Backend: PUT /notifications/read-all. */
export async function markAllNotificationsRead(): Promise<void> {
  if (USE_MOCK) {
    setMockNotifications(getMockNotifications().map((n) => ({ ...n, read: true })));
    return;
  }
  await backendRequest('/notifications/read-all', 'PUT');
}
