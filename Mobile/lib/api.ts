// Data-access layer for the pillbox dashboard.
// Backend mode: set EXPO_PUBLIC_PILLBOX_API_URL (FastAPI, e.g. http://192.168.1.10:8000) and every
// call goes to the real backend (contract: Backend/README.md, docs/DEVICE_CONTRACT.md).
// Mock mode: when that variable is unset, everything is served from in-memory state with an
// artificial delay, so the screen works without the smart device or the backend.

import { AppConfig } from '@/config';
import {
  ApiError,
  expireSession,
  fetchWithTimeout,
  getFreshAccessToken,
  refreshAccessToken,
  tokenExpiresAtMs,
} from '@/lib/api/client';
import { tokenStore } from '@/lib/api/token-store';
import { newCorrelationId, perfEnabled, perfLog } from '@/lib/perf';

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

export const BASE_URL = AppConfig.pillboxApiUrl;

export const USE_MOCK = BASE_URL === '';

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
  openSlots: [],
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

type SendOptions = { correlationId?: string };

async function send(
  path: string,
  method: Method,
  body: unknown,
  token: string | null,
  opts: SendOptions,
): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.correlationId) headers['X-Correlation-ID'] = opts.correlationId;
  try {
    return await fetchWithTimeout(`${BASE_URL}/api/v1${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new BackendError(0, 'NETWORK_ERROR', `Cannot reach the backend at ${BASE_URL}`);
  }
}

/** Access token for the backend; it verifies the same tokens the app's own API issues. */
async function accessToken(): Promise<string | null> {
  try {
    return await getFreshAccessToken();
  } catch (err) {
    if (err instanceof ApiError && err.code === 'UNAUTHORIZED') {
      throw new BackendError(401, 'UNAUTHORIZED', 'Session expired');
    }
    // Refresh endpoint unreachable: try the stored token; the backend decides.
    return tokenStore.getAccessToken();
  }
}

async function toBackendError(res: Response): Promise<BackendError> {
  let code = 'HTTP_ERROR';
  let message = `Backend request failed (${res.status})`;
  try {
    const err = (await res.json()) as { error?: { code?: string; message?: string } };
    code = err.error?.code ?? code;
    message = err.error?.message ?? message;
  } catch {
    // non-JSON error body
  }
  return new BackendError(res.status, code, message);
}

async function backend<T>(path: string, method: Method = 'GET', body?: unknown, opts: SendOptions = {}): Promise<T> {
  let res = await send(path, method, body, await accessToken(), opts);
  if (res.status === 401) {
    // Only an invalid/expired token is retried. Other 401s (e.g. DEVICE_PIN_INCORRECT) are final:
    // retrying them would replay the request and count a wrong PIN twice against the lockout.
    const err = await toBackendError(res);
    if (err.code !== 'UNAUTHORIZED') throw err;
    let fresh: string | null;
    try {
      fresh = await refreshAccessToken();
    } catch {
      throw new BackendError(0, 'NETWORK_ERROR', 'Cannot refresh the session');
    }
    if (!fresh) {
      await expireSession();
      throw err;
    }
    res = await send(path, method, body, fresh, opts);
  }
  if (!res.ok) throw await toBackendError(res);
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
  chambers?: { slot_number: number; door: 'OPEN' | 'CLOSED' }[];
};
type BackendSlotSchedule = {
  id: string | null;
  slot_number: number;
  window_start: string | null;
  window_end: string | null;
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

let cachedDeviceId: string | null = AppConfig.pinnedDeviceId;

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
  return { deviceName: detail.device_nickname ?? detail.device_code, ...toStatusFields(status) };
}

/** Everything in DeviceStatus except the name; also used for statuses pushed over /ws/app. */
export type DeviceStatusFields = Omit<DeviceStatus, 'deviceName'>;

function toStatusFields(status: BackendStatus): DeviceStatusFields {
  return {
    online: status.connectivity === 'ONLINE',
    batteryPercent: status.battery_percent ?? 0,
    wifiLabel: status.wifi_strength ? `Sinyal ${status.wifi_strength.toLowerCase()}` : '-',
    lastSyncedAt: status.last_seen_at ? Date.parse(status.last_seen_at) : 0,
    openSlots: (status.chambers ?? []).filter((c) => c.door === 'OPEN').map((c) => slotIdOf(c.slot_number)),
  };
}

type ScheduleState = {
  slots: Slot[];
  scheduleIds: Map<SlotId, string>;
  /** Backend rows by slot, to skip writes that would change nothing. */
  rows: Map<SlotId, BackendSlotSchedule>;
};

async function backendSchedules(): Promise<ScheduleState> {
  const id = await deviceId();
  const [schedules, stock] = await Promise.all([
    backend<BackendSlotSchedule[]>(`/devices/${id}/schedules`),
    backend<BackendStock[]>(`/devices/${id}/stock`),
  ]);
  const stockBySlot = new Map(stock.map((s) => [s.slot_number, s.remaining_units]));
  const scheduleIds = new Map<SlotId, string>();
  const rows = new Map<SlotId, BackendSlotSchedule>();
  const slots = schedules.map((s): Slot => {
    const slotId = slotIdOf(s.slot_number);
    rows.set(slotId, s);
    if (s.id) scheduleIds.set(slotId, s.id);
    return {
      id: slotId,
      timeMinutes: s.is_empty ? null : parseHHmm(s.window_start),
      enabled: !s.is_empty && s.active,
      toleranceMinutes: toTolerance(s.tolerance_minutes),
      stock: stockBySlot.get(s.slot_number) ?? 0,
      capacity: AppConfig.slotCapacity,
    };
  });
  return { slots, scheduleIds, rows };
}

/** Sachets per slot as last reported by the pillbox (heartbeat), without the schedules. */
export async function getStock(): Promise<Partial<Record<SlotId, number>>> {
  if (USE_MOCK) return Object.fromEntries(mockSchedules.map((s) => [s.id, s.stock]));
  const stock = await backend<BackendStock[]>(`/devices/${await deviceId()}/stock`);
  return Object.fromEntries(stock.map((s) => [slotIdOf(s.slot_number), s.remaining_units]));
}

/** True when PUT-ing these fields would leave the backend row exactly as it is. */
function isUnchanged(row: BackendSlotSchedule | undefined, fields: { window_start: string; window_end: string; tolerance_minutes: number; active: boolean }): boolean {
  return (
    row !== undefined &&
    !row.is_empty &&
    row.window_start === fields.window_start &&
    row.window_end === fields.window_end &&
    row.tolerance_minutes === fields.tolerance_minutes &&
    row.active === fields.active
  );
}

async function backendSaveSchedule(slots: Slot[]): Promise<Slot[]> {
  const id = await deviceId();
  const { scheduleIds, rows } = await backendSchedules();
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
      // Every PUT bumps the device config version and makes the device pull its config again, so
      // untouched slots are skipped. Writes stay sequential: their order avoids WINDOW_OVERLAP.
      if (isUnchanged(rows.get(slot.id), fields)) continue;
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
  const correlationId = perfEnabled() ? newCorrelationId() : undefined;
  const tappedAt = Date.now();
  perfLog('app_to_iot', 'app_button_tap', { correlation_id: correlationId });
  const id = await deviceId();
  try {
    await backend(
      `/devices/${id}/alarm`,
      'POST',
      { slot_number: slotId ? slotNumberOf(slotId) : null, duration_seconds: durationSeconds },
      { correlationId },
    );
    perfLog('app_to_iot', 'app_response_received', { correlation_id: correlationId, ok: true, ms: Date.now() - tappedAt });
  } catch (err) {
    const code = err instanceof BackendError ? err.code : 'UNKNOWN';
    perfLog('app_to_iot', 'app_response_received', { correlation_id: correlationId, ok: false, code, ms: Date.now() - tappedAt });
    throw err;
  }
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

// Notifications are written by the backend (telemetry, rules engine, presence monitor). The
// backend's /ws/app socket hints "refetch now" right after each commit (see the push section
// below); polling while at least one listener is subscribed is the fallback. Worst-case added
// delay without a socket = AppConfig.notificationPollMs + one request.
const seenNotificationIds = new Set<string>();
/** false until the first poll after (re)subscribing: that one only loads history. */
let historyLoaded = false;
let pollTimer: ReturnType<typeof setTimeout> | null = null;
let pollActive = false;
let pollGeneration = 0;

async function pollNotifications(): Promise<void> {
  const startedAt = Date.now();
  try {
    const page = await backend<BackendNotificationPage>(`/notifications?limit=${AppConfig.notificationPageSize}`);
    applyNotifications([...page.data].reverse(), 'app_fetched', startedAt); // oldest first
    historyLoaded = true;
  } catch (err) {
    console.warn('[pillbox] notification poll failed', err);
  }
}

/** Shows notifications not seen yet (from a poll or a push), oldest first. */
function applyNotifications(items: BackendNotification[], step: 'app_fetched' | 'app_pushed', startedAt: number): void {
  for (const n of items) {
    if (seenNotificationIds.has(n.id)) continue;
    seenNotificationIds.add(n.id);
    if (historyLoaded || step === 'app_pushed') {
      perfLog('iot_to_app', step, {
        notification_id: n.id,
        ms: Date.now() - startedAt,
        // Phone clock vs server clock; compare with the backend log for exact numbers.
        created_to_shown_ms: Date.now() - Date.parse(n.created_at),
      });
    }
    const app = toAppNotification(n);
    listeners.forEach((listener) => listener(app));
  }
}

// A setTimeout chain instead of setInterval, so a slow poll never overlaps the next one.
// The generation check ends an old loop when polling is stopped and restarted mid-request.
function startPolling(): void {
  if (pollActive) return;
  pollActive = true;
  const generation = ++pollGeneration;
  const loop = async () => {
    await pollNotifications();
    if (pollActive && generation === pollGeneration) {
      pollTimer = setTimeout(() => void loop(), AppConfig.notificationPollMs);
    }
  };
  void loop();
}

function stopPolling(): void {
  pollActive = false;
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = null;
}

// ---------------------------------------------------------------------------
// Push hints (Backend /ws/app, Backend/app/services/app_hub.py)
// The backend sends {"type":"notifications"} or {"type":"device"} right after a DB commit, so the
// dashboard refetches at once instead of on the next poll. The socket carries no data: the
// refetch goes through the normal authenticated endpoints. Polling keeps running as the fallback
// (socket down, hint lost).
// ---------------------------------------------------------------------------

/** status = new values pushed by the backend; null = something changed, refetch. */
export type DeviceChangeListener = (status: DeviceStatusFields | null) => void;

const deviceListeners = new Set<DeviceChangeListener>();

/** Called when the backend reports a change to the device (status, battery, doors, stock). */
export function subscribeToDeviceChanges(listener: DeviceChangeListener): () => void {
  deviceListeners.add(listener);
  return () => {
    deviceListeners.delete(listener);
  };
}

type PushMessage = {
  type?: string;
  items?: BackendNotification[];
  device_id?: string;
  status?: BackendStatus;
};

const RECONNECT_MIN_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

let socket: WebSocket | null = null;
let socketWanted = false;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectDelayMs = RECONNECT_MIN_MS;

function appSocketUrl(): string {
  return `${BASE_URL.replace(/^http/, 'ws')}/ws/app`;
}

async function openSocket(): Promise<void> {
  if (!socketWanted || socket) return;
  let token: string | null = null;
  try {
    token = await accessToken();
  } catch {
    // session expired: the auth provider signs out; retry in case it was transient
  }
  if (!socketWanted || socket) return; // stopped, or opened by another call, while awaiting
  if (!token) {
    scheduleReconnect();
    return;
  }
  const ws = new WebSocket(appSocketUrl());
  socket = ws;
  ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token }));
  ws.onmessage = (e) => {
    let message: PushMessage;
    try {
      message = JSON.parse(String(e.data)) as PushMessage;
    } catch {
      return;
    }
    const type = message.type;
    if (type === 'ready') {
      if (__DEV__) console.info('[pillbox] live updates connected');
      reconnectDelayMs = RECONNECT_MIN_MS;
      void pollNotifications(); // catch up on anything sent while disconnected
    } else if (type === 'notifications') {
      // The rows come with the message; an older backend sends none, so fetch them.
      if (message.items?.length) applyNotifications(message.items, 'app_pushed', Date.now());
      else void pollNotifications();
    } else if (type === 'device') {
      // Another device the user follows: this dashboard shows only cachedDeviceId.
      if (message.device_id && cachedDeviceId && message.device_id !== cachedDeviceId) return;
      if (__DEV__) console.info('[pillbox] device update pushed');
      const status = message.status ? toStatusFields(message.status) : null;
      deviceListeners.forEach((listener) => listener(status));
    }
  };
  ws.onclose = (e) => {
    if (socket === ws) socket = null;
    if (__DEV__ && socketWanted) console.info(`[pillbox] live updates disconnected (code ${e.code}), retrying`);
    scheduleReconnect();
  };
  // onerror is always followed by onclose, which reconnects.
}

function scheduleReconnect(): void {
  if (!socketWanted || reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    void openSocket();
  }, reconnectDelayMs);
  reconnectDelayMs = Math.min(reconnectDelayMs * 2, RECONNECT_MAX_MS);
}

function startSocket(): void {
  socketWanted = true;
  void openSocket();
}

function stopSocket(): void {
  socketWanted = false;
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = null;
  reconnectDelayMs = RECONNECT_MIN_MS;
  const ws = socket;
  socket = null;
  ws?.close();
}

/** Call after pairing or joining a pillbox, so the socket also covers the new device. */
export function resubscribeRealtime(): void {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'resubscribe' }));
}

// Refreshes the access token shortly before it expires, so a push-triggered refetch never waits
// for an inline refresh (getFreshAccessToken refreshes once less than tokenRefreshSkewMs is left).
let tokenTimer: ReturnType<typeof setTimeout> | null = null;

async function scheduleTokenRefresh(): Promise<void> {
  if (tokenTimer) clearTimeout(tokenTimer);
  tokenTimer = null;
  const token = await tokenStore.getAccessToken();
  const expiresAt = token ? tokenExpiresAtMs(token) : null;
  if (expiresAt === null || !socketWanted) return;
  const dueInMs = Math.max(expiresAt - AppConfig.tokenRefreshSkewMs + 1_000 - Date.now(), 1_000);
  tokenTimer = setTimeout(() => {
    tokenTimer = null;
    getFreshAccessToken()
      .catch(() => undefined) // offline or session over: the next request handles it
      .finally(() => void scheduleTokenRefresh());
  }, dueInMs);
}

function stopTokenRefresh(): void {
  if (tokenTimer) clearTimeout(tokenTimer);
  tokenTimer = null;
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
    historyLoaded = false;
    startPolling();
    startSocket();
    void scheduleTokenRefresh();
  }
  return () => {
    listeners.delete(listener);
    if (!USE_MOCK && listeners.size === 0) {
      stopPolling();
      stopSocket();
      stopTokenRefresh();
    }
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
