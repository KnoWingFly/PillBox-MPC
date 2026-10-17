// Single place for the app's tunable values. Everything here is PUBLIC: EXPO_PUBLIC_* variables are
// inlined into the JS bundle at build time (https://docs.expo.dev/guides/environment-variables/),
// so never put secrets here. Each variable must be read as `process.env.EXPO_PUBLIC_X` (dot notation)
// or Expo will not inline it.

function intFromEnv(raw: string | undefined, fallback: number, min = 0): number {
  const value = Number.parseInt(raw ?? '', 10);
  return Number.isFinite(value) && value >= min ? value : fallback;
}

const trimSlash = (url: string) => url.replace(/\/+$/, '');

export const AppConfig = {
  /** Expo API routes (auth, settings). Empty = same dev server as the bundle (see lib/api/client.ts). */
  apiUrl: trimSlash(process.env.EXPO_PUBLIC_API_URL ?? ''),
  /** FastAPI pillbox backend. Empty = the dashboard uses mock data. */
  pillboxApiUrl: trimSlash(process.env.EXPO_PUBLIC_PILLBOX_API_URL ?? ''),
  /** Optional: pin the dashboard to one device id. Empty = first paired device. */
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

  /** true = log "[perf]" timing lines (see src/lib/perf.ts). */
  perfTimingLogs: process.env.EXPO_PUBLIC_PERF_TIMING_LOGS === 'true',
} as const;
