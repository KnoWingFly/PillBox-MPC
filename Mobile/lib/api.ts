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
  AdherenceSummary,
  AppNotification,
  DeviceStatus,
  DoseEventType,
  NotificationAction,
  NotificationSeverity,
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

/** One entry of a 422 VALIDATION_ERROR body, e.g. { path: 'body.full_name', message }. */
export type BackendErrorDetail = { path: string; message: string };

export class BackendError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    /** Field-level problems for VALIDATION_ERROR; empty otherwise. */
    public readonly details: readonly BackendErrorDetail[] = [],
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
  } catch (err) {
    // The server got the request but did not answer in time (slow database): a write may still
    // have been applied, so say so instead of claiming the backend is unreachable.
    if (err instanceof Error && err.message === 'Request timed out') {
      throw new BackendError(
        0,
        'TIMEOUT',
        method === 'GET'
          ? 'Server terlalu lama merespons. Coba lagi sebentar lagi.'
          : 'Server terlalu lama merespons. Perubahan mungkin sudah tersimpan: tarik ke bawah untuk memuat ulang sebelum mencoba lagi.',
      );
    }
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
  let details: BackendErrorDetail[] = [];
  try {
    const err = (await res.json()) as { error?: { code?: string; message?: string; details?: unknown } };
    code = err.error?.code ?? code;
    message = err.error?.message ?? message;
    const raw = err.error?.details;
    if (Array.isArray(raw)) {
      details = raw.filter(
        (d): d is BackendErrorDetail => typeof d?.path === 'string' && typeof d?.message === 'string',
      );
    } else if (code === 'DEVICE_REJECTED_COMMAND') {
      // The pillbox's own reason (e.g. "Bilik lain sedang terbuka") says more than "Device rejected the command".
      const deviceReason = (raw as { error?: unknown } | undefined)?.error;
      if (typeof deviceReason === 'string') message = deviceReason;
    }
  } catch {
    // non-JSON error body
  }
  return new BackendError(res.status, code, message, details);
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

/** For lib/devices.ts (the device service): same auth, refresh and error handling. */
export const backendRequest = backend;

// --- backend response shapes (subset of what the API returns) ---------------

type BackendDeviceDetail = { id: string; device_nickname: string | null; device_code: string };
type BackendStatus = {
  connectivity: 'ONLINE' | 'OFFLINE';
  last_seen_at: string | null;
  wifi_strength: 'LEMAH' | 'SEDANG' | 'KUAT' | null;
  battery_percent: number | null;
  chambers?: { slot_number: number; door: 'OPEN' | 'CLOSED' }[];
  device_time?: string | null;
  clock_speed?: number | null;
  follow_device_clock?: boolean;
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
  severity: 'INFO' | 'WARNING' | 'CRITICAL';
  elderly_id: string | null;
  device_id: string | null;
  slot_number: number | null;
  delay_minutes: number | null;
  message: string;
  is_read: boolean;
  created_at: string;
  actions?: NotificationAction[];
};

const SEVERITY: Record<BackendNotification['severity'], NotificationSeverity> = {
  INFO: 'info',
  WARNING: 'warning',
  CRITICAL: 'critical',
};
type BackendNotificationPage = { data: BackendNotification[]; unread_count: number; total: number };
type BackendJournalSummary = {
  total_scheduled: number;
  taken_on_time: number;
  taken_late: number;
  missed: number;
  /** Percent of decided doses that were taken (late counts as taken). */
  compliance_rate: number | null;
  avg_delay_minutes: number | null;
};

// The pillbox every device-scoped call targets. Chosen by DevicesProvider (context/devices-context.tsx);
// null = none selected yet, and device-scoped calls fail with NO_DEVICE instead of guessing one.
let activeDeviceId: string | null = null;
let activeElderlyId: string | null = null;
/** Pillboxes removed this session: late pushes and polls about them are ignored. */
const removedDeviceIds = new Set<string>();

/** Points every device-scoped call, the live notification stream and the feed at one pillbox. */
export function setActivePillbox(pillbox: { id: string; elderlyId: string | null } | null): void {
  if (pillbox?.id === activeDeviceId && pillbox?.elderlyId === activeElderlyId) return;
  activeDeviceId = pillbox?.id ?? null;
  activeElderlyId = pillbox?.elderlyId ?? null;
  seenNotificationIds.clear();
  historyLoaded = false;
}

export function markPillboxRemoved(id: string): void {
  removedDeviceIds.add(id);
  if (activeDeviceId === id) setActivePillbox(null);
}

/**
 * Whether a notification belongs on screen for the active pillbox: its own events, plus
 * elderly-level ones without a device (same elderly profile). Mock mode has one pillbox.
 * TODO(backend-branch): GET /notifications?device_id= would make this a server filter (handoff 4).
 */
export function inActiveScope(n: Pick<AppNotification, 'deviceId' | 'elderlyId'>): boolean {
  if (USE_MOCK) return true;
  if (!activeDeviceId) return false;
  if (n.deviceId && removedDeviceIds.has(n.deviceId)) return false;
  if (n.deviceId) return n.deviceId === activeDeviceId;
  return n.elderlyId !== null && n.elderlyId === activeElderlyId;
}

/** The active pillbox's elderly profile (journal and adherence are per elderly, not per device). */
export function activePillboxElderlyId(): string | null {
  return activeElderlyId;
}

/** Forgets everything tied to the signed-in account. Call on login and logout. */
export function resetPillboxSession(): void {
  activeDeviceId = null;
  activeElderlyId = null;
  removedDeviceIds.clear();
  seenNotificationIds.clear();
  historyLoaded = false;
}

async function elderlyId(): Promise<string> {
  if (activeElderlyId) return activeElderlyId;
  throw new BackendError(404, 'NO_DEVICE', 'No pillbox selected.');
}

async function deviceId(): Promise<string> {
  if (activeDeviceId) return activeDeviceId;
  throw new BackendError(404, 'NO_DEVICE', 'No pillbox selected.');
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
    clock:
      status.follow_device_clock && status.device_time
        ? { deviceTimeMs: Date.parse(status.device_time), speed: status.clock_speed ?? 1, receivedAt: Date.now() }
        : null,
  };
}

type ScheduleState = {
  slots: Slot[];
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
  const rows = new Map<SlotId, BackendSlotSchedule>();
  const slots = schedules.map((s): Slot => {
    const slotId = slotIdOf(s.slot_number);
    rows.set(slotId, s);
    return {
      id: slotId,
      timeMinutes: s.is_empty ? null : parseHHmm(s.window_start),
      enabled: !s.is_empty && s.active,
      toleranceMinutes: toTolerance(s.tolerance_minutes),
      stock: stockBySlot.get(s.slot_number) ?? 0,
      capacity: AppConfig.slotCapacity,
    };
  });
  return { slots, rows };
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
  const { slots: current, rows } = await backendSchedules();
  // Only slots that change are sent, all in one request: the backend saves them in one transaction
  // (one device lock, one config version, one push to the pillbox) and checks WINDOW_OVERLAP on the
  // final state, so the order does not matter. One write per slot was slow on a remote database.
  const changes: Record<string, unknown>[] = [];
  for (const slot of slots) {
    const slotNumber = slotNumberOf(slot.id);
    const row = rows.get(slot.id);
    if (slot.timeMinutes === null) {
      if (row && !row.is_empty) changes.push({ slot_number: slotNumber, clear: true });
      continue;
    }
    // The dashboard edits a single time per slot, so the window is [time, time] and
    // tolerance_minutes is the grace period (see Backend/app/services/adherence.py).
    const time = formatTime(slot.timeMinutes);
    const fields = { window_start: time, window_end: time, tolerance_minutes: slot.toleranceMinutes, active: slot.enabled };
    if (isUnchanged(row, fields)) continue;
    changes.push({ slot_number: slotNumber, ...fields, ...(row && !row.is_empty ? {} : { days_of_week: [1, 2, 3, 4, 5, 6, 7] }) });
  }
  if (changes.length === 0) return current;
  const saved = await backend<BackendSlotSchedule[]>(`/devices/${id}/schedules`, 'PUT', { slots: changes });
  const stock = new Map(current.map((s) => [s.id, s.stock]));
  return saved.map((s): Slot => {
    const slotId = slotIdOf(s.slot_number);
    return {
      id: slotId,
      timeMinutes: s.is_empty ? null : parseHHmm(s.window_start),
      enabled: !s.is_empty && s.active,
      toleranceMinutes: toTolerance(s.tolerance_minutes),
      stock: stock.get(slotId) ?? 0,
      capacity: AppConfig.slotCapacity,
    };
  });
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
    severity: SEVERITY[n.severity] ?? 'info',
    slotId: n.slot_number ? slotIdOf(n.slot_number) : null,
    title: NOTIFICATION_TITLES[n.type],
    message: n.message,
    createdAt: Date.parse(n.created_at),
    read: n.is_read,
    deviceId: n.device_id ?? null,
    elderlyId: n.elderly_id ?? null,
    ...(type === 'late' && n.delay_minutes !== null ? { minutesLate: n.delay_minutes } : {}),
    ...(n.actions?.length ? { actions: n.actions } : {}),
    // A forced open right after a missed dose: probably taken late, not a break-in.
    ...(n.type === 'UNSCHEDULED_OPEN' && n.actions?.includes('CONFIRM_TAKEN') ? { title: 'Mungkin Diminum Terlambat' } : {}),
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
    // The first poll after subscribing only learns what already exists: the list loads history
    // itself (lib/notifications.ts), so replaying it here would re-toast and double-count unread.
    if (!historyLoaded && step === 'app_fetched') continue;
    if (historyLoaded || step === 'app_pushed') {
      perfLog('iot_to_app', step, {
        notification_id: n.id,
        ms: Date.now() - startedAt,
        // Phone clock vs server clock; compare with the backend log for exact numbers.
        created_to_shown_ms: Date.now() - Date.parse(n.created_at),
      });
    }
    const app = toAppNotification(n);
    if (!inActiveScope(app)) continue; // another (or a removed) pillbox: shown when it is selected
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
      pollTimer = setTimeout(() => void loop(), isRealtimeLive() ? REALTIME_FALLBACK_POLL_MS : AppConfig.notificationPollMs);
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
// The backend sends {"type":"notifications","items"} or {"type":"device","status"} right after a DB
// commit; the data is applied directly, and only a message without data triggers a refetch through
// the normal authenticated endpoints. Polling keeps running as the fallback (socket down, push lost).
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

/**
 * While the push socket is live, polling is only a safety net for a lost hint, so it slows
 * down to this period. With many app users this keeps the backend (and its shared database)
 * from answering a request per user every few seconds.
 */
export const REALTIME_FALLBACK_POLL_MS = 60_000;

let socket: WebSocket | null = null;
/** true from the backend's "ready" until the socket closes. */
let socketReady = false;
let socketWanted = false;

/** The backend's push socket is connected and authenticated. */
export function isRealtimeLive(): boolean {
  return socketReady && socket?.readyState === WebSocket.OPEN;
}
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
      socketReady = true;
      if (__DEV__) console.info('[pillbox] live updates connected');
      reconnectDelayMs = RECONNECT_MIN_MS;
      void pollNotifications(); // catch up on anything sent while disconnected
    } else if (type === 'notifications') {
      // The rows come with the message; an older backend sends none, so fetch them.
      if (message.items?.length) applyNotifications(message.items, 'app_pushed', Date.now());
      else void pollNotifications();
    } else if (type === 'device') {
      // Another device the user follows: this dashboard shows only the active pillbox.
      if (message.device_id && message.device_id !== activeDeviceId) return;
      if (__DEV__) console.info('[pillbox] device update pushed');
      const status = message.status ? toStatusFields(message.status) : null;
      deviceListeners.forEach((listener) => listener(status));
    }
  };
  ws.onclose = (e) => {
    if (socket === ws) {
      socket = null;
      socketReady = false;
    }
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
  socketReady = false;
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

/** Mock "server" table of notifications, newest first. Read and changed only via lib/notifications.ts. */
let mockNotifications: AppNotification[] = [];

export function getMockNotifications(): readonly AppNotification[] {
  return mockNotifications;
}

export function setMockNotifications(next: AppNotification[]): void {
  mockNotifications = next;
}

/** Mock dose log, kept apart from notifications so deleting notifications never changes adherence. */
const mockDoseLog: { type: DoseEventType; minutesLate: number }[] = [];

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
  const createdAt = Date.now();
  const notification: AppNotification = {
    ...input,
    // Zero-padded so ids sort in creation order; they break ties between equal createdAt values.
    id: `n-${createdAt}-${String(notificationSeq).padStart(6, '0')}`,
    createdAt,
    read: false,
  };
  mockNotifications = [notification, ...mockNotifications];
  if (input.type !== 'system') {
    mockDoseLog.push({ type: input.type, minutesLate: input.minutesLate ?? 0 });
  }
  listeners.forEach((listener) => listener(notification));
  return notification;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Mock only: adds `count` past notifications (one every 30 min, going back from the oldest one
 * stored) so pagination can be tested. Not pushed to listeners: pull to refresh to see them.
 */
export async function seedMockHistory(count = 45): Promise<void> {
  if (!USE_MOCK) return mockOnly('seedMockHistory');
  await delay();
  const oldest = mockNotifications.reduce((min, n) => Math.min(min, n.createdAt), Date.now());
  const kinds: DoseEventType[] = ['on_time', 'late', 'missed', 'on_time', 'late'];
  const seeded: AppNotification[] = [];
  for (let i = 1; i <= count; i += 1) {
    notificationSeq += 1;
    const type = kinds[i % kinds.length];
    const slotId = mockSchedules.find((s) => s.timeMinutes !== null && s.enabled)?.id ?? 'A1';
    const createdAt = oldest - i * 30 * 60 * 1000;
    const minutesLate = type === 'late' ? 10 + (i % 4) * 5 : undefined;
    seeded.push({
      id: `n-${createdAt}-${String(notificationSeq).padStart(6, '0')}`,
      type,
      severity: type === 'missed' ? 'critical' : type === 'late' ? 'warning' : 'info',
      slotId,
      title: { on_time: 'Obat Diminum Tepat Waktu', late: 'Obat Diminum Terlambat', missed: 'Dosis Terlewat' }[type],
      message: `Riwayat contoh #${i} untuk slot ${slotId}.`,
      createdAt,
      read: i > 3,
      ...(minutesLate !== undefined ? { minutesLate } : {}),
    });
    mockDoseLog.push({ type, minutesLate: minutesLate ?? 0 });
  }
  mockNotifications = [...mockNotifications, ...seeded];
}

/** Backend tabs of GET /notifications (Backend/app/services/notification_feed.py). */
export type BackendFeedTab = 'ALL' | 'LATE_MISSED';

/** One page of the caregiver's notification feed from the backend, newest first. */
export async function fetchBackendNotifications(
  tab: BackendFeedTab,
  page: number,
  limit: number,
  elderlyId: string | null = null,
): Promise<{ items: AppNotification[]; total: number; unreadCount: number }> {
  const query = new URLSearchParams({ tab, page: String(page), limit: String(limit) });
  if (elderlyId) query.set('elderly_id', elderlyId);
  const res = await backend<BackendNotificationPage>(`/notifications?${query.toString()}`);
  return { items: res.data.map(toAppNotification), total: res.total, unreadCount: res.unread_count };
}

export async function markBackendNotificationRead(id: string): Promise<void> {
  await backend(`/notifications/${id}/read`, 'PUT');
}

/** Deletes the caller's copy of one notification; already gone (404) counts as done. */
export async function deleteBackendNotification(id: string): Promise<void> {
  try {
    await backend<void>(`/notifications/${id}`, 'DELETE');
  } catch (err) {
    if (!(err instanceof BackendError && err.status === 404)) throw err;
  }
}

/** Days covered by the adherence card in backend mode (today included, WIB). */
const ADHERENCE_DAYS = 30;

/** "YYYY-MM-DD" in Asia/Jakarta (UTC+7, no DST), `daysAgo` days before today. */
function jakartaDate(daysAgo: number): string {
  return new Date(Date.now() + 7 * 3600_000 - daysAgo * 86_400_000).toISOString().slice(0, 10);
}

/**
 * Dose adherence for the dashboard card. Independent of the notification list.
 * Backend: GET /elderly/{elderly_id}/journal/summary for the last 30 days.
 */
export async function getAdherenceSummary(): Promise<AdherenceSummary> {
  if (!USE_MOCK) {
    const id = await elderlyId();
    const s = await backend<BackendJournalSummary>(
      `/elderly/${id}/journal/summary?start=${jakartaDate(ADHERENCE_DAYS - 1)}&end=${jakartaDate(0)}`,
    );
    return {
      totalDoses: s.taken_on_time + s.taken_late + s.missed,
      onTimeDoses: s.taken_on_time,
      lateDoses: s.taken_late,
      missedDoses: s.missed,
      adherencePercent: s.compliance_rate === null ? null : Math.round(s.compliance_rate),
      averageDelayMinutes: s.avg_delay_minutes === null ? null : Math.round(s.avg_delay_minutes),
      periodLabel: `${ADHERENCE_DAYS} hari terakhir`,
    };
  }
  let onTime = 0;
  let late = 0;
  let missed = 0;
  let delaySum = 0;
  for (const dose of mockDoseLog) {
    if (dose.type === 'on_time') onTime += 1;
    else if (dose.type === 'late') {
      late += 1;
      delaySum += dose.minutesLate;
    } else missed += 1;
  }
  const total = onTime + late + missed;
  const taken = onTime + late;
  return {
    totalDoses: total,
    onTimeDoses: onTime,
    lateDoses: late,
    missedDoses: missed,
    // Same definition as the backend's compliance_rate: taken (on time or late) / decided doses.
    adherencePercent: total > 0 ? Math.round((taken / total) * 100) : null,
    averageDelayMinutes: taken > 0 ? Math.round(delaySum / taken) : null,
  };
}

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
          severity: 'info',
          slotId: null,
          title: 'Sistem Terkoneksi',
          message: `${mockDevice.deviceName} kembali online dan jadwal tersinkron.`,
        }
      : {
          type: 'system',
          severity: 'warning',
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
/** "Buka bilik sekarang" on a missed dose: the pillbox pops the chamber up again for a short time;
 * opening it records the dose as taken late. Returns when it closes again (pillbox clock, ISO). */
export async function releaseMissedDose(notificationId: string, pin: string): Promise<{ releaseUntil: string }> {
  if (USE_MOCK) mockOnly('releaseMissedDose');
  const res = await backend<{ release_until: string }>(`/notifications/${notificationId}/late-release`, 'POST', {
    device_pin: pin,
  });
  return { releaseUntil: res.release_until };
}

/** "Sudah diminum" on a missed dose (or a forced open after one): recorded as taken late. */
export async function confirmDoseTaken(notificationId: string): Promise<void> {
  if (USE_MOCK) mockOnly('confirmDoseTaken');
  await backend(`/notifications/${notificationId}/confirm-taken`, 'POST', {});
}

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
        severity: 'info',
        slotId: input.slotId,
        title: 'Obat Diminum Tepat Waktu',
        message: `Obat ${where} diminum sesuai jadwal ${time}.`,
      });
    case 'late': {
      const minutesLate = Math.max(1, input.minutesLate ?? 0);
      return emitNotification({
        type: 'late',
        severity: 'warning',
        slotId: input.slotId,
        title: 'Obat Diminum Terlambat',
        message: `Obat ${where} diminum terlambat ${minutesLate} menit dari jadwal ${time}.`,
        minutesLate,
      });
    }
    case 'missed':
      return emitNotification({
        type: 'missed',
        severity: 'critical',
        slotId: input.slotId,
        title: 'Dosis Terlewat',
        message: `Dosis ${where} jadwal ${time} tidak diminum. Segera hubungi lansia.`,
      });
  }
}
