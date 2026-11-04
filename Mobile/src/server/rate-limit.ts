// Attempt limits for the auth endpoints, stored in auth_attempts (prisma/schema.prisma AuthAttempt)
// so they hold across restarts and across server processes. Each call counts and checks in ONE
// atomic statement BEFORE the expensive work (bcrypt, email), so parallel requests cannot slip
// past the limit.
import type { AttemptLimit } from './config';
import { sha256Hex } from './crypto';
import { db } from './db';
import { tooManyAttempts } from './errors';

export type AttemptScope =
  | 'login:email'
  | 'login:ip'
  | 'register:ip'
  | 'forgot:email'
  | 'forgot:ip'
  | 'reset:email';

const MS_PER_SECOND = 1000;

/** Keys are hashed: the table never holds an email address or IP in clear. */
function attemptKey(scope: AttemptScope, value: string): Promise<string> {
  return sha256Hex(`${scope}:${value}`);
}

/**
 * Counts one attempt for `value` in `scope`. Throws 429 TOO_MANY_ATTEMPTS (with Retry-After) when
 * the key is locked or this attempt goes over the limit. `value` null (unknown IP) is not limited.
 */
export async function consumeAttempt(scope: AttemptScope, value: string | null, limit: AttemptLimit): Promise<void> {
  if (!value) return;
  const key = await attemptKey(scope, value);
  const windowSeconds = Math.ceil(limit.windowMs / MS_PER_SECOND);
  const lockSeconds = Math.ceil(limit.lockMs / MS_PER_SECOND);
  // A window older than windowSeconds starts over at 1. Going over `max` sets locked_until, which
  // an attempt during the lock never extends or clears.
  const rows = await db.$queryRaw<{ count: number; retry_after: number | null }[]>`
    INSERT INTO auth_attempts (key, count, window_start, locked_until)
    VALUES (${key}, 1, now(), NULL)
    ON CONFLICT (key) DO UPDATE SET
      count = CASE WHEN auth_attempts.window_start <= now() - ${windowSeconds}::int * interval '1 second'
                   THEN 1 ELSE auth_attempts.count + 1 END,
      window_start = CASE WHEN auth_attempts.window_start <= now() - ${windowSeconds}::int * interval '1 second'
                          THEN now() ELSE auth_attempts.window_start END,
      locked_until = CASE
        WHEN auth_attempts.locked_until > now() THEN auth_attempts.locked_until
        WHEN auth_attempts.window_start > now() - ${windowSeconds}::int * interval '1 second'
             AND auth_attempts.count + 1 > ${limit.max}::int
          THEN now() + ${lockSeconds}::int * interval '1 second'
        ELSE NULL END
    RETURNING count, EXTRACT(EPOCH FROM (locked_until - now()))::float8 AS retry_after`;
  const row = rows[0];
  if (row && row.retry_after !== null && row.retry_after > 0) throw tooManyAttempts(row.retry_after);
}

/** Forgets the attempts of `value` in `scope`, e.g. after a successful login. */
export async function clearAttempts(scope: AttemptScope, value: string): Promise<void> {
  await db.authAttempt.deleteMany({ where: { key: await attemptKey(scope, value) } });
}
