// Single place for the app's tunable values. Everything here is PUBLIC: EXPO_PUBLIC_* variables are
// inlined into the JS bundle at build time (https://docs.expo.dev/guides/environment-variables/),
// so never put secrets here. Each variable must be read as `process.env.EXPO_PUBLIC_X` (dot notation)
// or Expo will not inline it.

import Constants from 'expo-constants';
import { Platform } from 'react-native';

function intFromEnv(raw: string | undefined, fallback: number, min = 0): number {
  const value = Number.parseInt(raw ?? '', 10);
  return Number.isFinite(value) && value >= min ? value : fallback;
}

const trimSlash = (url: string) => url.replace(/\/+$/, '');

/**
 * EXPO_PUBLIC_PILLBOX_API_URL=auto (or auto:<port>, default 8000) = the backend runs on the same
 * machine that serves the app, so a changed Wi-Fi IP needs no edit and no restart:
 * web uses the page's host, a phone in development uses the Expo dev server's host.
 */
function resolvePillboxUrl(raw: string): string {
  const auto = /^auto(?::(\d{1,5}))?$/i.exec(raw.trim());
  if (!auto) return trimSlash(raw.trim());
  const port = auto[1] ?? '8000';
  const host =
    Platform.OS === 'web'
      ? typeof window !== 'undefined'
        ? window.location.hostname
        : ''
      : (Constants.expoConfig?.hostUri?.split(':')[0] ?? '');
  // No page / dev server to follow (server render, or a release build): assume this machine.
  return `http://${host || 'localhost'}:${port}`;
}

export const AppConfig = {
  /** Expo API routes (auth, settings). Empty = same dev server as the bundle (see lib/api/client.ts). */
  apiUrl: trimSlash(process.env.EXPO_PUBLIC_API_URL ?? ''),
  /** FastAPI pillbox backend. Empty = the dashboard uses mock data; "auto" = same host as the app. */
  pillboxApiUrl: resolvePillboxUrl(process.env.EXPO_PUBLIC_PILLBOX_API_URL ?? ''),
  /** Optional: pillbox selected first when the account has no saved choice. Empty = first one. */
  pinnedDeviceId: process.env.EXPO_PUBLIC_PILLBOX_DEVICE_ID || null,

  /** Abort a request after this long (ms). Must exceed the backend's COMMAND_ACK_TIMEOUT_SECONDS. */
  requestTimeoutMs: intFromEnv(process.env.EXPO_PUBLIC_API_TIMEOUT_MS, 20_000, 1_000),
  /** Notification feed polling period (ms). Worst-case delay before a new alert appears. */
  notificationPollMs: intFromEnv(process.env.EXPO_PUBLIC_NOTIFICATION_POLL_MS, 5_000, 1_000),
  /** Device status (online, battery) polling period (ms). */
  deviceStatusPollMs: intFromEnv(process.env.EXPO_PUBLIC_DEVICE_STATUS_POLL_MS, 10_000, 1_000),
  /** Notifications fetched per poll. */
  notificationPageSize: intFromEnv(process.env.EXPO_PUBLIC_NOTIFICATION_PAGE_SIZE, 50, 1),
  /** Refresh the access token this long before its `exp` (ms), so a request never starts with a dead token. */
  tokenRefreshSkewMs: 30_000,

  /** Sachets per compartment; keep equal to the backend's STOCK_CAPACITY_PER_SLOT. */
  slotCapacity: intFromEnv(process.env.EXPO_PUBLIC_SLOT_CAPACITY, 30, 1),
  /** Placeholder phone number for the "call" action until elderly profiles carry one. */
  elderPhone: process.env.EXPO_PUBLIC_ELDER_PHONE || '+620000000000',
  /** Used when the device reports no IANA timezone. */
  fallbackTimezone: 'Asia/Jakarta',

  /** Elderly profile limits; keep equal to the backend's ELDERLY_NAME_MIN_LENGTH / ELDERLY_MAX_AGE_YEARS. */
  elderlyNameMinLength: 2,
  elderlyNameMaxLength: 100,
  elderlyMaxAgeYears: 120,
  /** Where the birth-date picker opens when nothing is picked yet (a typical elderly age). */
  elderlyPickerDefaultAgeYears: 70,
  /**
   * Indonesian phone numbers: country code and the national digit count (after 0 / 62 / +62).
   * Client-only UX rule; the backend accepts any E.164 number.
   */
  phoneCountryCode: '62',
  phoneNationalMinDigits: 9,
  phoneNationalMaxDigits: 13,

  /** true = log "[perf]" timing lines (see src/lib/perf.ts). */
  perfTimingLogs: process.env.EXPO_PUBLIC_PERF_TIMING_LOGS === 'true',
} as const;
