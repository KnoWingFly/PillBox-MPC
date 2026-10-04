// Data-access layer for the pillbox test harness.
// USE_MOCK = true serves everything from in-memory state with an artificial delay, so the
// screen works without the IoT simulator or the FastAPI backend.

import type {
  AppNotification,
  DeviceStatus,
  DoseEventType,
  Slot,
  SlotId,
  ToleranceMinutes,
} from './types';

export const USE_MOCK = true;

// TODO(backend): set to the FastAPI base URL and implement the real branches below once the
// endpoint paths are agreed with the backend team. Do not guess paths here.
export const BASE_URL = 'http://REPLACE_WITH_BACKEND_HOST:8000';

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

function notImplemented(name: string): never {
  // TODO(backend): replace with a fetch to `${BASE_URL}/...` once the API contract is agreed.
  throw new Error(`${name}: real backend mode is not implemented yet (BASE_URL=${BASE_URL})`);
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
  return () => {
    listeners.delete(listener);
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
  if (!USE_MOCK) return notImplemented('getDeviceStatus');
  await delay();
  return { ...mockDevice };
}

/** Mock only: flips the simulated connection and emits a system notification. */
export async function setDeviceConnection(online: boolean): Promise<DeviceStatus> {
  if (!USE_MOCK) return notImplemented('setDeviceConnection');
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
  if (!USE_MOCK) return notImplemented('getSchedules');
  await delay();
  return cloneSlots(mockSchedules);
}

export async function saveSchedule(slots: Slot[]): Promise<Slot[]> {
  if (!USE_MOCK) return notImplemented('saveSchedule');
  await delay();
  mockSchedules = cloneSlots(slots);
  mockDevice = { ...mockDevice, lastSyncedAt: Date.now() };
  return cloneSlots(mockSchedules);
}

/** Rings the pillbox alarm, e.g. after a late or missed dose. */
export async function triggerAlarm(slotId: SlotId | null): Promise<{ slotId: SlotId | null }> {
  if (!USE_MOCK) return notImplemented('triggerAlarm');
  await delay();
  return { slotId };
}

/** Fires a test reminder (LED + buzzer) on a single compartment. */
export async function triggerTestSlot(slotId: SlotId): Promise<{ slotId: SlotId }> {
  if (!USE_MOCK) return notImplemented('triggerTestSlot');
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
  if (!USE_MOCK) return notImplemented('simulateDoseEvent');
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
