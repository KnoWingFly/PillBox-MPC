// Server-only latency logs for the Expo API routes (PERF_TIMING_LOGS=true in Mobile/.env; not an
// EXPO_PUBLIC_ variable, so it never reaches the bundle). Logs ids and durations only.

const enabled = process.env.PERF_TIMING_LOGS === 'true';

const SAFE_ID = /^[A-Za-z0-9._:-]{1,64}$/;

export function correlationIdOf(request: Request): string | null {
  const value = request.headers.get('x-correlation-id');
  return value && SAFE_ID.test(value) ? value : null;
}

export function serverPerfLog(request: Request, step: string, fields: Record<string, unknown> = {}): void {
  if (!enabled) return;
  console.log(
    '[perf]',
    JSON.stringify({ flow: 'login', step, correlation_id: correlationIdOf(request), path: new URL(request.url).pathname, ...fields }),
  );
}

/** Runs fn and logs how long it took under `step`. */
export async function timed<T>(request: Request, step: string, fn: () => Promise<T>): Promise<T> {
  if (!enabled) return fn();
  const started = performance.now();
  try {
    return await fn();
  } finally {
    serverPerfLog(request, step, { ms: Math.round(performance.now() - started) });
  }
}
