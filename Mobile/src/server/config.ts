// Tunable auth-server limits. Server-only env (never EXPO_PUBLIC_): each value has a safe default,
// so none of these variables is required. Read with dot notation; see .env.example.

function intFromEnv(raw: string | undefined, fallback: number, min = 0): number {
  const value = Number.parseInt(raw ?? '', 10);
  return Number.isFinite(value) && value >= min ? value : fallback;
}

const MINUTE_MS = 60_000;

/** At most `max` attempts per `windowMs`; going over locks the key for `lockMs`. */
export type AttemptLimit = { max: number; windowMs: number; lockMs: number };

function limit(max: string | undefined, maxDefault: number, windowMinutes: string | undefined, windowDefault: number): AttemptLimit {
  const windowMs = intFromEnv(windowMinutes, windowDefault, 1) * MINUTE_MS;
  return { max: intFromEnv(max, maxDefault, 1), windowMs, lockMs: windowMs };
}

const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

export const serverConfig = {
  /**
   * A session (refresh-token family) ends this long after sign-in, however often it is refreshed:
   * rotation keeps the first token's expiry (Mobile/BACKEND_HANDOFF.md item 9).
   */
  refreshTokenTtlMs: intFromEnv(process.env.REFRESH_TOKEN_TTL_DAYS, 30, 1) * DAY_MS,
  /** Session length when "Ingat saya" is off (`remember: false` on login / Google sign-in). */
  refreshTokenShortTtlMs: intFromEnv(process.env.REFRESH_TOKEN_SHORT_TTL_HOURS, 12, 1) * HOUR_MS,
  /** HttpOnly cookie that carries the web app's refresh token, sent only to the auth routes. */
  refreshCookie: { name: 'pillcare_refresh', path: '/api/auth' },
  /**
   * A refresh token presented again this soon after it was rotated (a retry after a lost response,
   * two tabs refreshing at once) gets a fresh pair instead of revoking the whole session.
   */
  refreshReuseGraceMs: intFromEnv(process.env.REFRESH_REUSE_GRACE_MS, 10_000),
  /** Setting the first password on a Google-only account needs a sign-in at most this old. */
  passwordReauthWindowMs: intFromEnv(process.env.PASSWORD_REAUTH_WINDOW_MINUTES, 5, 1) * MINUTE_MS,
  /** Abort the email provider request after this long (ms). */
  emailSendTimeoutMs: intFromEnv(process.env.EMAIL_SEND_TIMEOUT_MS, 10_000, 1_000),
  /** Seconds suggested in Retry-After when the database is unavailable. */
  dbUnavailableRetryAfterSeconds: 5,

  limits: {
    loginPerEmail: limit(process.env.RATE_LOGIN_PER_EMAIL, 10, process.env.RATE_LOGIN_WINDOW_MINUTES, 15),
    loginPerIp: limit(process.env.RATE_LOGIN_PER_IP, 50, process.env.RATE_LOGIN_WINDOW_MINUTES, 15),
    registerPerIp: limit(process.env.RATE_REGISTER_PER_IP, 10, process.env.RATE_REGISTER_WINDOW_MINUTES, 60),
    forgotPerEmail: limit(process.env.RATE_FORGOT_PER_EMAIL, 5, process.env.RATE_FORGOT_WINDOW_MINUTES, 60),
    forgotPerIp: limit(process.env.RATE_FORGOT_PER_IP, 20, process.env.RATE_FORGOT_WINDOW_MINUTES, 60),
    resetPerEmail: limit(process.env.RATE_RESET_PER_EMAIL, 10, process.env.RATE_RESET_WINDOW_MINUTES, 60),
  },
} as const;
