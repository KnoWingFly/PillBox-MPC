// Data-access layer for the pillbox dashboard.
// Backend mode: set EXPO_PUBLIC_PILLBOX_API_URL (FastAPI, e.g. http://192.168.1.10:8000) and every
// call goes to the real backend (contract: Backend/README.md, docs/DEVICE_CONTRACT.md).
// Mock mode: when that variable is unset, everything is served from in-memory state with an
// artificial delay, so the screen works without the smart device or the backend.

import { settingApi } from '@/lib/api/setting';
import { tokenStore } from '@/lib/api/token-store';

import { SLOT_IDS } from './types';
import type {
  AppNotification,
  DeviceStatus,
  DoseEventType,
  NotificationType,
  Slot,
  SlotId,
  ToleranceMinutes,
} from './types';

export const BASE_URL = (process.env.EXPO_PUBLIC_PILLBOX_API_URL ?? '').replace(/\/+$/, '');

export const USE_MOCK = BASE_URL === '';

// Optional: pin the dashboard to one device id. Unset = the first device the caregiver can see.
const PINNED_DEVICE_ID = process.env.EXPO_PUBLIC_PILLBOX_DEVICE_ID || null;

/** Sachet capacity per compartment (backend STOCK_CAPACITY_PER_SLOT default). */
const SLOT_CAPACITY = 30;
const NOTIFICATION_POLL_MS = 5000;

// ---------------------------------------------------------------------------
// Helpers shared with the UI
// ---------------------------------------------------------------------------

const ROW_LABELS: Record<'A' | 'B', string> = { A: 'Sebelum Makan', B: 'Sesudah Makan' };
const COLUMN_LABELS = ['Pagi', 'Siang', 'Sore', 'Malam'] as const;

export function getSlotRowLabel(id: SlotId): string {
  return ROW_LABELS[id[0] as 'A' | 'B'];
}

export function getSlotColumnLabel(id: SlotId): string {
  return COLUMN_LABELS[Number(id[1]) - 1];
}

export function formatTime(minutes: number | null): string {
  if (minutes === null) return '--:--';
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

// ---------------------------------------------------------------------------
// Mock state
// ---------------------------------------------------------------------------

const DEFAULT_TOLERANCE: ToleranceMinutes = 30;

function hm(h: number, m: number): number {
  return h * 60 + m;
}

function makeSlot(id: SlotId, timeMinutes: number | null): Slot {
  const empty = timeMinutes === null;
  return {
    id,
    timeMinutes,
    enabled: !empty,
    toleranceMinutes: DEFAULT_TOLERANCE,
    stock: empty ? 0 : 7,
    capacity: 7,
  };
}

let mockSchedules: Slot[] = [
  makeSlot('A1', hm(7, 0)),
  makeSlot('A2', hm(11, 45)),
  makeSlot('A3', null),
  makeSlot('A4', hm(21, 0)),
  makeSlot('B1', hm(8, 15)),
  makeSlot('B2', hm(12, 45)),
  makeSlot('B3', hm(18, 45)),
  makeSlot('B4', null),
];

let mockDevice: DeviceStatus = {
  deviceName: 'Pillbox 1',
  online: true,
  batteryPercent: 86,
  wifiLabel: 'Rumah_WiFi',
  lastSyncedAt: Date.now() - 2 * 60 * 1000,
};

function delay(): Promise<void> {
  const ms = 300 + Math.round(Math.random() * 200);
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function cloneSlots(slots: Slot[]): Slot[] {
  return slots.map((s) => ({ ...s }));
}

function mockOnly(name: string): never {
  throw new Error(
    `${name} only exists in mock mode. With the real backend, use the smart device emulator ` +
      '(Wi-Fi toggle, opening compartments) to produce these events.',
  );
}

// ---------------------------------------------------------------------------
// Real backend client (FastAPI, /api/v1)
// ---------------------------------------------------------------------------

export class BackendError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'BackendError';
  }
}

type Method = 'GET' | 'POST' | 'PUT' | 'DELETE';

async function send(path: string, method: Method, body: unknown, token: string | null): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;
  try {
    return await fetch(`${BASE_URL}/api/v1${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new BackendError(0, 'NETWORK_ERROR', `Cannot reach the backend at ${BASE_URL}`);
  }
}

async function backend<T>(path: string, method: Method = 'GET', body?: unknown): Promise<T> {
  let res = await send(path, method, body, await tokenStore.getAccessToken());
  if (res.status === 401) {
    // The backend verifies the same access token the app's own API issues. When it has
    // expired, any authenticated call to the app's API rotates it (src/lib/api/client.ts),
    // then the request is retried once with the new token.
    await settingApi.get();
    res = await send(path, method, body, await tokenStore.getAccessToken());
  }
  if (!res.ok) {
    let code = 'HTTP_ERROR';
    let message = `Backend request failed (${res.status})`;
    try {
      const err = (await res.json()) as { error?: { code?: string; message?: string } };
      code = err.error?.code ?? code;
      message = err.error?.message ?? message;
    } catch {
      // non-JSON error body
    }
    throw new BackendError(res.status, code, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// --- backend response shapes (subset of what the API returns) ---------------

type BackendDeviceList = { data: { id: string; device_nickname: string | null }[]; total: number };
type BackendDeviceDetail = { id: string; device_nickname: string | null; device_code: string };
type BackendStatus = {
  connectivity: 'ONLINE' | 'OFFLINE';
  last_seen_at: string | null;
  wifi_strength: 'LEMAH' | 'SEDANG' | 'KUAT' | null;
  battery_percent: number | null;
};
type BackendSlotSchedule = {
  id: string | null;
  slot_number: number;
  window_start: string | null;
  tolerance_minutes: number | null;
  active: boolean;
  is_empty: boolean;
};
type BackendStock = { slot_number: number; remaining_units: number };
type BackendNotification = {
  id: string;
  type: 'DOSE_TAKEN' | 'DOSE_LATE' | 'DOSE_MISSED' | 'DEVICE_OFFLINE' | 'DEVICE_ONLINE' | 'LOW_BATTERY' | 'UNSCHEDULED_OPEN';
  slot_number: number | null;
  delay_minutes: number | null;
  message: string;
  is_read: boolean;
  created_at: string;
};
type BackendNotificationPage = { data: BackendNotification[] };

let cachedDeviceId: string | null = PINNED_DEVICE_ID;

async function deviceId(): Promise<string> {
  if (cachedDeviceId) return cachedDeviceId;
  const list = await backend<BackendDeviceList>('/devices');
  if (list.data.length === 0) {
    throw new BackendError(404, 'NO_DEVICE', 'No paired pillbox yet. Pair a device first.');
  }
  cachedDeviceId = list.data[0].id;
  return cachedDeviceId;
}

export interface ConnectPillboxInput {
  /** Code shown in the emulator's "Koneksi Server" panel, e.g. PB-1A2B3C4D (or a scanned QR payload). */
  deviceCode: string;
  /** New 4-digit PIN for a fresh device, or the existing PIN to join a device another caregiver paired. */
  pin: string;
  nickname: string;
  /** Used only when the caregiver has no elderly profile yet. */
  elderlyName: string;
}

export interface ConnectPillboxResult {
  deviceId: string;
  /** true = joined an already-paired device as PEMANTAU (read-only). */
  joined: boolean;
}

/** Pairs a registered pillbox to the signed-in caregiver (or joins it with its PIN). */
export async function connectPillbox(input: ConnectPillboxInput): Promise<ConnectPillboxResult> {
  if (USE_MOCK) return mockOnly('connectPillbox');
  const code = input.deviceCode.trim();
  const scan = await backend<{ device_id: string; is_registered: boolean }>('/devices/pairing/scan', 'POST', {
    device_qr_payload: code,
  });
  if (scan.is_registered) {
    await backend(`/devices/${scan.device_id}/join`, 'POST', { device_pin: input.pin });
  } else {
    const elderly = await backend<{ data: { id: string; my_role: string }[] }>('/elderly?limit=100');
    let elderlyId = elderly.data.find((e) => e.my_role === 'OWNER' || e.my_role === 'ADMIN')?.id;
    if (!elderlyId) {
      const created = await backend<{ id: string }>('/elderly', 'POST', {
        full_name: input.elderlyName.trim() || 'Lansia',
      });
      elderlyId = created.id;
    }
    // timezone omitted: the backend uses the caregiver's own timezone from their profile.
    await backend('/devices', 'POST', {
      device_qr_payload: code,
      elderly_id: elderlyId,
      device_nickname: input.nickname.trim() || 'Pillbox Lansia',
      device_pin: input.pin,
    });
  }
  cachedDeviceId = scan.device_id;
  return { deviceId: scan.device_id, joined: scan.is_registered };
}

function slotIdOf(slotNumber: number): SlotId {
  return SLOT_IDS[slotNumber - 1];
}

function slotNumberOf(id: SlotId): number {
  return SLOT_IDS.indexOf(id) + 1;
}

function parseHHmm(value: string | null): number | null {
  if (!value) return null;
  const [h, m] = value.split(':').map(Number);
  return h * 60 + m;
}

function toTolerance(value: number | null): ToleranceMinutes {
  return value === 15 || value === 45 || value === 60 ? value : 30;
}

async function backendDeviceStatus(): Promise<DeviceStatus> {
  const id = await deviceId();
  const [detail, status] = await Promise.all([
    backend<BackendDeviceDetail>(`/devices/${id}`),
    backend<BackendStatus>(`/devices/${id}/status`),
  ]);
  return {
    deviceName: detail.device_nickname ?? detail.device_code,
    online: status.connectivity === 'ONLINE',
    batteryPercent: status.battery_percent ?? 0,
    wifiLabel: status.wifi_strength ? `Sinyal ${status.wifi_strength.toLowerCase()}` : '-',
    lastSyncedAt: status.last_seen_at ? Date.parse(status.last_seen_at) : 0,
  };
}

async function backendSchedules(): Promise<{ slots: Slot[]; scheduleIds: Map<SlotId, string> }> {
  const id = await deviceId();
  const [schedules, stock] = await Promise.all([
    backend<BackendSlotSchedule[]>(`/devices/${id}/schedules`),
    backend<BackendStock[]>(`/devices/${id}/stock`),
  ]);
  const stockBySlot = new Map(stock.map((s) => [s.slot_number, s.remaining_units]));
  const scheduleIds = new Map<SlotId, string>();
  const slots = schedules.map((s): Slot => {
    const slotId = slotIdOf(s.slot_number);
    if (s.id) scheduleIds.set(slotId, s.id);
    return {
      id: slotId,
      timeMinutes: s.is_empty ? null : parseHHmm(s.window_start),
      enabled: !s.is_empty && s.active,
      toleranceMinutes: toTolerance(s.tolerance_minutes),
      stock: stockBySlot.get(s.slot_number) ?? 0,
      capacity: SLOT_CAPACITY,
    };
  });
  return { slots, scheduleIds };
}

async function backendSaveSchedule(slots: Slot[]): Promise<Slot[]> {
  const id = await deviceId();
  const { scheduleIds } = await backendSchedules();
  // Clear/deactivate first so moving a time from one slot to another never trips the
  // backend's WINDOW_OVERLAP check halfway through.
  const ordered = [...slots].sort((a, b) => Number(a.enabled && a.timeMinutes !== null) - Number(b.enabled && b.timeMinutes !== null));
  for (const slot of ordered) {
    const existing = scheduleIds.get(slot.id);
    if (slot.timeMinutes === null) {
      if (existing) await backend<void>(`/devices/${id}/schedules/${existing}`, 'DELETE');
      continue;
    }
    // The dashboard edits a single time per slot, so the window is [time, time] and
    // tolerance_minutes is the grace period (see Backend/app/services/adherence.py).
    const time = formatTime(slot.timeMinutes);
    const fields = {
      window_start: time,
      window_end: time,
      tolerance_minutes: slot.toleranceMinutes,
      active: slot.enabled,
    };
    if (existing) {
      await backend(`/devices/${id}/schedules/${existing}`, 'PUT', fields);
    } else {
      await backend(`/devices/${id}/schedules`, 'POST', {
        ...fields,
        slot_number: slotNumberOf(slot.id),
        days_of_week: [1, 2, 3, 4, 5, 6, 7],
      });
    }
  }
  return (await backendSchedules()).slots;
}

async function backendAlarm(slotId: SlotId | null, durationSeconds: number): Promise<void> {
  const id = await deviceId();
  await backend(`/devices/${id}/alarm`, 'POST', {
    slot_number: slotId ? slotNumberOf(slotId) : null,
    duration_seconds: durationSeconds,
  });
}

const NOTIFICATION_TITLES: Record<BackendNotification['type'], string> = {
  DOSE_TAKEN: 'Obat Diminum Tepat Waktu',
  DOSE_LATE: 'Obat Diminum Terlambat',
  DOSE_MISSED: 'Dosis Terlewat',
  DEVICE_OFFLINE: 'Perangkat Terputus',
  DEVICE_ONLINE: 'Sistem Terkoneksi',
  LOW_BATTERY: 'Baterai Lemah',
  UNSCHEDULED_OPEN: 'Bilik Dibuka di Luar Jadwal',
};

function toAppNotification(n: BackendNotification): AppNotification {
  const typeMap: Partial<Record<BackendNotification['type'], NotificationType>> = {
    DOSE_TAKEN: 'on_time',
    DOSE_LATE: 'late',
    DOSE_MISSED: 'missed',
  };
  const type = typeMap[n.type] ?? 'system';
  return {
    id: n.id,
    type,
    slotId: n.slot_number ? slotIdOf(n.slot_number) : null,
    title: NOTIFICATION_TITLES[n.type],
    message: n.message,
    createdAt: Date.parse(n.created_at),
    read: n.is_read,
    ...(type === 'late' && n.delay_minutes !== null ? { minutesLate: n.delay_minutes } : {}),
  };
}

// Notifications are written by the backend (telemetry, rules engine, presence monitor);
// the dashboard receives them by polling while at least one listener is subscribed.
const seenNotificationIds = new Set<string>();
let pollTimer: ReturnType<typeof setInterval> | null = null;

async function pollNotifications(): Promise<void> {
  try {
    const page = await backend<BackendNotificationPage>('/notifications?limit=50');
    const fresh = page.data.filter((n) => !seenNotificationIds.has(n.id)).reverse(); // oldest first
    for (const n of fresh) {
      seenNotificationIds.add(n.id);
      const app = toAppNotification(n);
      listeners.forEach((listener) => listener(app));
    }
  } catch (err) {
    console.warn('[pillbox] notification poll failed', err);
  }
}

function startPolling(): void {
  if (pollTimer) return;
  void pollNotifications();
  pollTimer = setInterval(() => void pollNotifications(), NOTIFICATION_POLL_MS);
}

function stopPolling(): void {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

// ---------------------------------------------------------------------------
// Notification emitter
// Notifications are produced locally (simulator buttons, connection toggle), so a tiny
// listener set is enough. A real backend would push these over WebSocket/SSE instead.
// ---------------------------------------------------------------------------

export type NotificationListener = (notification: AppNotification) => void;

const listeners = new Set<NotificationListener>();
let notificationSeq = 0;

/** Registers a listener and returns an unsubscribe function. */
export function subscribeToNotifications(listener: NotificationListener): () => void {
  listeners.add(listener);
  if (!USE_MOCK) {
    // A new subscriber (e.g. a remounted screen) gets the recent history again.
    seenNotificationIds.clear();
    startPolling();
  }
  return () => {
    listeners.delete(listener);
    if (!USE_MOCK && listeners.size === 0) stopPolling();
  };
}

function emitNotification(input: Omit<AppNotification, 'id' | 'createdAt' | 'read'>): AppNotification {
  notificationSeq += 1;
  const notification: AppNotification = {
    ...input,
    id: `n-${Date.now()}-${notificationSeq}`,
    createdAt: Date.now(),
    read: false,
  };
  listeners.forEach((listener) => listener(notification));
  return notification;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function getDeviceStatus(): Promise<DeviceStatus> {
  if (!USE_MOCK) return backendDeviceStatus();
  await delay();
  return { ...mockDevice };
}

/** Mock only: flips the simulated connection and emits a system notification. */
export async function setDeviceConnection(online: boolean): Promise<DeviceStatus> {
  if (!USE_MOCK) return mockOnly('setDeviceConnection');
  await delay();
  mockDevice = {
    ...mockDevice,
    online,
    lastSyncedAt: online ? Date.now() : mockDevice.lastSyncedAt,
  };
  emitNotification(
    online
      ? {
          type: 'system',
          slotId: null,
          title: 'Sistem Terkoneksi',
          message: `${mockDevice.deviceName} kembali online dan jadwal tersinkron.`,
        }
      : {
          type: 'system',
          slotId: null,
          title: 'Perangkat Terputus',
          message: `${mockDevice.deviceName} tidak terhubung. Periksa daya dan Wi-Fi.`,
        },
  );
  return { ...mockDevice };
}

export async function getSchedules(): Promise<Slot[]> {
  if (!USE_MOCK) return (await backendSchedules()).slots;
  await delay();
  return cloneSlots(mockSchedules);
}

export async function saveSchedule(slots: Slot[]): Promise<Slot[]> {
  if (!USE_MOCK) return backendSaveSchedule(slots);
  await delay();
  mockSchedules = cloneSlots(slots);
  mockDevice = { ...mockDevice, lastSyncedAt: Date.now() };
  return cloneSlots(mockSchedules);
}

/** Rings the pillbox alarm, e.g. after a late or missed dose. */
export async function triggerAlarm(slotId: SlotId | null): Promise<{ slotId: SlotId | null }> {
  if (!USE_MOCK) {
    await backendAlarm(slotId, 60);
    return { slotId };
  }
  await delay();
  return { slotId };
}

/** Fires a test reminder (LED + buzzer) on a single compartment. */
export async function triggerTestSlot(slotId: SlotId): Promise<{ slotId: SlotId }> {
  if (!USE_MOCK) {
    await backendAlarm(slotId, 10);
    return { slotId };
  }
  await delay();
  return { slotId };
}

export interface SimulateDoseInput {
  slotId: SlotId;
  type: DoseEventType;
  /** Required for `late`; ignored otherwise. */
  minutesLate?: number;
}

/**
 * Mock only: emulates what the IoT simulator would report for a dose and emits the matching
 * notification. Uses the schedule last saved to the pillbox.
 */
export async function simulateDoseEvent(input: SimulateDoseInput): Promise<AppNotification> {
  if (!USE_MOCK) return mockOnly('simulateDoseEvent');
  await delay();
  const slot = mockSchedules.find((s) => s.id === input.slotId);
  const time = formatTime(slot?.timeMinutes ?? null);
  const where = `${input.slotId} (${getSlotColumnLabel(input.slotId)}, ${getSlotRowLabel(input.slotId)})`;

  switch (input.type) {
    case 'on_time':
      return emitNotification({
        type: 'on_time',
        slotId: input.slotId,
        title: 'Obat Diminum Tepat Waktu',
        message: `Obat ${where} diminum sesuai jadwal ${time}.`,
      });
    case 'late': {
      const minutesLate = Math.max(1, input.minutesLate ?? 0);
      return emitNotification({
        type: 'late',
        slotId: input.slotId,
        title: 'Obat Diminum Terlambat',
        message: `Obat ${where} diminum terlambat ${minutesLate} menit dari jadwal ${time}.`,
        minutesLate,
      });
    }
    case 'missed':
      return emitNotification({
        type: 'missed',
        slotId: input.slotId,
        title: 'Dosis Terlewat',
        message: `Dosis ${where} jadwal ${time} tidak diminum. Segera hubungi lansia.`,
      });
  }
}
