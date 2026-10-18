// Device service: the ONLY place that lists, pairs, renames, removes or hides pillboxes.
// The UI (context/devices-context.tsx) applies changes optimistically and rolls back when a call
// here throws, so wiring the remaining backend endpoints later needs no UI change.
//
// Ownership model (Backend/migrations/0001): a pillbox belongs to an ELDERLY profile, and users
// reach it through their role on that profile (OWNER / ADMIN / PEMANTAU). So one pillbox can be
// on several accounts, and unpairing it (OWNER only) removes it for every caregiver.
import AsyncStorage from '@react-native-async-storage/async-storage';

import {
  BackendError,
  backendRequest as backend,
  deleteBackendNotification,
  fetchBackendNotifications,
  getDeviceStatus,
  USE_MOCK,
} from './api';
import type { AppNotification } from './types';

export type PillboxRole = 'OWNER' | 'ADMIN' | 'PEMANTAU';

export interface Pillbox {
  id: string;
  /** PB-XXXXXXXX, as shown on the pillbox. */
  code: string;
  name: string;
  elderlyId: string | null;
  elderlyName: string | null;
  online: boolean;
  batteryPercent: number | null;
  /** Epoch ms of the last signal from the pillbox; null = never seen. */
  lastSeenAt: number | null;
  /** This caregiver's role on the pillbox's elderly profile; null = unknown. */
  myRole: PillboxRole | null;
}

export interface ElderlyProfile {
  id: string;
  name: string;
  myRole: PillboxRole;
}

/** OWNER and ADMIN can rename a pillbox and pair new ones to the profile (backend EDITOR_ROLES). */
export function canEdit(role: PillboxRole | null): boolean {
  return role === 'OWNER' || role === 'ADMIN';
}

/** Only the OWNER can unpair (Backend/app/services/device_management.py, DELETE /devices/{id}). */
export function canUnpair(role: PillboxRole | null): boolean {
  return role === 'OWNER';
}

// --- backend shapes -------------------------------------------------------------

type DeviceListItem = {
  id: string;
  device_code: string;
  device_nickname: string | null;
  elderly_id: string | null;
  elderly_nickname: string | null;
  connectivity: 'ONLINE' | 'OFFLINE';
  battery_percent: number | null;
  last_seen_at: string | null;
};
type ElderlyListItem = { id: string; full_name: string; nickname: string | null; my_role: PillboxRole };

const MOCK_ID = 'mock-pillbox';

function mockUnsupported(): never {
  throw new BackendError(400, 'MOCK_UNSUPPORTED', 'Tidak tersedia di mode data contoh.');
}

async function elderlyProfiles(): Promise<ElderlyListItem[]> {
  // TODO(backend-branch): more than 100 elderly profiles would need paging.
  return (await backend<{ data: ElderlyListItem[] }>('/elderly?limit=100')).data;
}

// --- list -----------------------------------------------------------------------

/** Every pillbox this caregiver can see, with their role on each. */
export async function listPillboxes(): Promise<Pillbox[]> {
  if (USE_MOCK) {
    const status = await getDeviceStatus();
    return [
      {
        id: MOCK_ID,
        code: 'PB-00000000',
        name: status.deviceName,
        elderlyId: null,
        elderlyName: null,
        online: status.online,
        batteryPercent: status.batteryPercent,
        lastSeenAt: status.lastSyncedAt,
        myRole: 'OWNER',
      },
    ];
  }
  const [devices, profiles] = await Promise.all([
    backend<{ data: DeviceListItem[] }>('/devices'),
    elderlyProfiles(),
  ]);
  const roleOf = new Map(profiles.map((p) => [p.id, p.my_role]));
  return devices.data.map((d) => ({
    id: d.id,
    code: d.device_code,
    name: d.device_nickname?.trim() || d.device_code,
    elderlyId: d.elderly_id,
    elderlyName: d.elderly_nickname,
    online: d.connectivity === 'ONLINE',
    batteryPercent: d.battery_percent,
    lastSeenAt: d.last_seen_at ? Date.parse(d.last_seen_at) : null,
    myRole: (d.elderly_id && roleOf.get(d.elderly_id)) || null,
  }));
}

/** Elderly profiles a new pillbox can be paired to (OWNER / ADMIN only). */
export async function listPairableProfiles(): Promise<ElderlyProfile[]> {
  if (USE_MOCK) return [];
  return (await elderlyProfiles())
    .filter((p) => canEdit(p.my_role))
    .map((p) => ({ id: p.id, name: p.nickname || p.full_name, myRole: p.my_role }));
}

// --- add (pair or join) -----------------------------------------------------------

/** Result of looking a pairing code up, before the caregiver types a PIN. */
export interface PairingCheck {
  /** Normalized code, e.g. PB-1A2B3C4D (already validated by parsePairingPayload). */
  code: string;
  deviceId: string;
  /** 'pair' = nobody owns it yet (new PIN); 'join' = another caregiver paired it (their PIN, read-only role). */
  mode: 'pair' | 'join';
  /** Elderly profile the pillbox belongs to, when mode is 'join'. */
  elderlyName: string | null;
}

/**
 * Looks a validated code up. Throws BackendError QR_CODE_NOT_RECOGNIZED for an unknown code and
 * DEVICE_ALREADY_MINE when the pillbox is already on this account.
 * TODO(backend-branch): /pairing/scan is not rate limited and returns the elderly name to any
 * signed-in user (handoff items 1 and 2).
 */
export async function checkPairingCode(code: string): Promise<PairingCheck> {
  if (USE_MOCK) return mockUnsupported();
  const [scan, mine] = await Promise.all([
    backend<{ device_id: string; is_registered: boolean; elderly_name_if_owned: string | null }>(
      '/devices/pairing/scan',
      'POST',
      { device_qr_payload: code },
    ),
    backend<{ data: { id: string }[] }>('/devices'),
  ]);
  if (mine.data.some((d) => d.id === scan.device_id)) {
    throw new BackendError(409, 'DEVICE_ALREADY_MINE', 'This pillbox is already linked to your account.');
  }
  return {
    code,
    deviceId: scan.device_id,
    mode: scan.is_registered ? 'join' : 'pair',
    elderlyName: scan.is_registered ? scan.elderly_name_if_owned : null,
  };
}

export interface ConnectPillboxInput {
  check: PairingCheck;
  /** New 4-digit PIN when pairing, or the existing PIN when joining. */
  pin: string;
  nickname: string;
  /** Pairing only: an existing profile, or a name for a new one. */
  elderly: { id: string } | { newName: string };
}

export interface ConnectPillboxResult {
  deviceId: string;
  /** true = joined an already-paired pillbox as PEMANTAU (read-only). */
  joined: boolean;
  /** false = paired, but the pillbox is not connected to the server right now; null = unknown. */
  online: boolean | null;
}

/** Pairs a registered pillbox to an elderly profile (or joins it with its PIN). */
export async function connectPillbox(input: ConnectPillboxInput): Promise<ConnectPillboxResult> {
  if (USE_MOCK) return mockUnsupported();
  const { code, deviceId, mode } = input.check;
  if (mode === 'join') {
    await backend(`/devices/${deviceId}/join`, 'POST', { device_pin: input.pin });
  } else {
    const elderlyId =
      'id' in input.elderly
        ? input.elderly.id
        : (await backend<{ id: string }>('/elderly', 'POST', { full_name: input.elderly.newName.trim() || 'Lansia' })).id;
    // timezone omitted: the backend uses the caregiver's own timezone from their profile.
    await backend('/devices', 'POST', {
      device_qr_payload: code,
      elderly_id: elderlyId,
      device_nickname: input.nickname.trim() || 'Pillbox Lansia',
      device_pin: input.pin,
    });
  }
  // Pairing succeeds even if the pillbox has never connected: report it so the UI can warn.
  const online = await backend<{ connectivity: 'ONLINE' | 'OFFLINE' }>(`/devices/${deviceId}/status`)
    .then((s) => s.connectivity === 'ONLINE')
    .catch(() => null);
  return { deviceId, joined: mode === 'join', online };
}

// --- rename -----------------------------------------------------------------------

export const PILLBOX_NAME_MAX = 100; // Backend Name100 (schemas/common.py)

/** PUT /devices/{id} {device_nickname}. OWNER / ADMIN only (server-enforced). */
export async function renamePillbox(id: string, name: string): Promise<void> {
  if (USE_MOCK) return mockUnsupported();
  await backend(`/devices/${id}`, 'PUT', { device_nickname: name.trim() });
}

// --- remove -----------------------------------------------------------------------

/** Most notifications scanned when deleting by device (100 per page). */
const MAX_SCAN_PAGES = 30;
const DELETE_CONCURRENCY = 4;

/**
 * Deletes the CALLER's notifications that `match` (never other caregivers' copies: the backend
 * scopes DELETE /notifications/{id} to the owner). Collects ids first, then deletes, so paging
 * offsets do not shift under the scan.
 * TODO(backend-branch): replace with DELETE /notifications?device_id= (handoff item 3).
 */
export async function deleteMyNotificationsWhere(
  match: (n: AppNotification) => boolean,
  elderlyId: string | null,
): Promise<{ deleted: number; failed: number }> {
  const ids: string[] = [];
  for (let page = 1; page <= MAX_SCAN_PAGES; page++) {
    const res = await fetchBackendNotifications('ALL', page, 100, elderlyId);
    ids.push(...res.items.filter(match).map((n) => n.id));
    if (res.items.length < 100) break;
  }
  let deleted = 0;
  let failed = 0;
  for (let i = 0; i < ids.length; i += DELETE_CONCURRENCY) {
    const results = await Promise.allSettled(ids.slice(i, i + DELETE_CONCURRENCY).map(deleteBackendNotification));
    for (const r of results) {
      if (r.status === 'fulfilled') deleted++;
      else failed++;
    }
  }
  return { deleted, failed };
}

/**
 * Unpairs a pillbox for EVERY caregiver of its elderly profile (OWNER only, server-enforced), then
 * deletes this caregiver's notification history for it.
 * The unpair itself (Backend device_management.unpair) soft-deletes the pillbox's schedules,
 * removes pending doses and clears its PIN and nickname. Notifications are not touched by the
 * backend, so the history purge is a second, best-effort step: `notificationsFailed` > 0 means
 * some rows are left and can be deleted from the Notifikasi tab.
 * TODO(backend-branch): DELETE /devices/{id}?purge_my_notifications=true (handoff item 5).
 */
export async function unpairPillbox(
  pillbox: Pick<Pillbox, 'id' | 'elderlyId'>,
): Promise<{ notificationsDeleted: number; notificationsFailed: number }> {
  if (USE_MOCK) return mockUnsupported();
  await backend(`/devices/${pillbox.id}`, 'DELETE');
  const purge = await deleteMyNotificationsWhere((n) => n.deviceId === pillbox.id, pillbox.elderlyId).catch(
    () => ({ deleted: 0, failed: -1 }),
  );
  return { notificationsDeleted: purge.deleted, notificationsFailed: purge.failed };
}

// --- per-account preferences on this phone -----------------------------------------
// Not secrets (device UUIDs), so AsyncStorage rather than SecureStore. Keyed by user, so a second
// account on the same phone never inherits the first one's choices.

const activeKey = (userId: string) => `pillcare.active_pillbox.${userId}`;
const hiddenKey = (userId: string) => `pillcare.hidden_pillboxes.${userId}`;

export async function loadActivePillboxId(userId: string): Promise<string | null> {
  return AsyncStorage.getItem(activeKey(userId)).catch(() => null);
}

export async function saveActivePillboxId(userId: string, id: string | null): Promise<void> {
  await (id ? AsyncStorage.setItem(activeKey(userId), id) : AsyncStorage.removeItem(activeKey(userId))).catch(
    () => undefined,
  );
}

/**
 * Pillboxes a non-owner chose to hide. The backend has no per-device "leave" for PEMANTAU/ADMIN
 * (their role is on the whole elderly profile), so hiding is local to this phone.
 * TODO(backend-branch): DELETE /devices/{id}/membership (handoff item 6).
 */
export async function loadHiddenPillboxIds(userId: string): Promise<string[]> {
  try {
    const raw = await AsyncStorage.getItem(hiddenKey(userId));
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

export async function saveHiddenPillboxIds(userId: string, ids: string[]): Promise<void> {
  await AsyncStorage.setItem(hiddenKey(userId), JSON.stringify(ids));
}
