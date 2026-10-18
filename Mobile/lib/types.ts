// Shared types for the Smart Pillbox caregiver test harness.

export const SLOT_IDS = ['A1', 'A2', 'A3', 'A4', 'B1', 'B2', 'B3', 'B4'] as const;

/** Row A = before meal, row B = after meal; columns 1-4 = morning, noon, afternoon, night. */
export type SlotId = (typeof SLOT_IDS)[number];

export type ToleranceMinutes = 15 | 30 | 45 | 60;

export interface Slot {
  id: SlotId;
  /** Scheduled time as minutes since midnight; null when the slot has no schedule (empty). */
  timeMinutes: number | null;
  enabled: boolean;
  toleranceMinutes: ToleranceMinutes;
  stock: number;
  capacity: number;
}

export interface DeviceStatus {
  deviceName: string;
  online: boolean;
  batteryPercent: number;
  wifiLabel: string;
  /** Epoch milliseconds of the last successful sync. */
  lastSyncedAt: number;
  /** Compartments whose door the pillbox last reported as open. */
  openSlots: SlotId[];
  /** The pillbox's own clock, when the backend judges doses by it; null = use the phone clock. */
  clock?: PillboxClock | null;
}

/** A reading of the pillbox clock (backend `device_time`). The emulator's lab clock can be moved
 * and sped up for demos, so "today" and "next dose" follow this rather than the phone. */
export interface PillboxClock {
  /** Pillbox time (epoch ms) at `receivedAt`. */
  deviceTimeMs: number;
  /** Pillbox seconds per real second: 1 = real time, the emulator can run 10x or 60x. */
  speed: number;
  /** Phone time (epoch ms) when the reading arrived. */
  receivedAt: number;
}

export type NotificationType = 'on_time' | 'late' | 'missed' | 'system';

export type DoseEventType = Exclude<NotificationType, 'system'>;

/** Mirrors the backend `severity` column. `critical` system alerts (e.g. a compartment opened
 * outside its schedule) stay under the "Sistem" filter but are styled as urgent. */
export type NotificationSeverity = 'info' | 'warning' | 'critical';

export interface AppNotification {
  id: string;
  type: NotificationType;
  severity: NotificationSeverity;
  slotId: SlotId | null;
  title: string;
  message: string;
  /** Epoch milliseconds. */
  createdAt: number;
  read: boolean;
  /** Only set for `late` notifications. */
  minutesLate?: number;
  /** What the caregiver can still do about it (backend `actions`; only on open, still-missed doses). */
  actions?: NotificationAction[];
  /** Pillbox the notification is about; null for elderly-level ones and in mock mode. */
  deviceId?: string | null;
  elderlyId?: string | null;
}

/** LATE_RELEASE = "Buka bilik sekarang" (device PIN), CONFIRM_TAKEN = "Sudah diminum". */
export type NotificationAction = 'LATE_RELEASE' | 'CONFIRM_TAKEN';

export interface AdherenceSummary {
  totalDoses: number;
  onTimeDoses: number;
  lateDoses: number;
  missedDoses: number;
  /** Taken doses (on time or late) / decided doses, in percent; null when none are recorded yet. */
  adherencePercent: number | null;
  /** Average delay across taken doses (on-time counts as 0); null when none were taken. */
  averageDelayMinutes: number | null;
  /** Period the numbers cover, e.g. "30 hari terakhir"; undefined = everything recorded. */
  periodLabel?: string;
}
