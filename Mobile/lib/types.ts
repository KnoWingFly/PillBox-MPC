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
}

export type NotificationType = 'on_time' | 'late' | 'missed' | 'system';

export type DoseEventType = Exclude<NotificationType, 'system'>;

export interface AppNotification {
  id: string;
  type: NotificationType;
  slotId: SlotId | null;
  title: string;
  message: string;
  /** Epoch milliseconds. */
  createdAt: number;
  read: boolean;
  /** Only set for `late` notifications. */
  minutesLate?: number;
}

export interface AdherenceSummary {
  totalDoses: number;
  onTimeDoses: number;
  lateDoses: number;
  missedDoses: number;
  /** null when no doses have been recorded yet. */
  adherencePercent: number | null;
  /** Average delay across taken doses (on-time counts as 0); null when none were taken. */
  averageDelayMinutes: number | null;
}
