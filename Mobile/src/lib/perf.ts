// Opt-in latency logs (EXPO_PUBLIC_PERF_TIMING_LOGS=true). One console line per step:
//   [perf] {"flow":"login","step":"session_restored","correlation_id":"...","ms":123}
// Only ids and durations are logged, never tokens, emails or names. When disabled every call
// returns immediately.

import { AppConfig } from '@/config';

export type PerfFlow = 'login' | 'iot_to_app' | 'app_to_iot';

const enabled = AppConfig.perfTimingLogs;

/** Process-relative clock; module load time approximates app start for the login flow. */
const appStartedAt = Date.now();

export function perfEnabled(): boolean {
  return enabled;
}

/** Short opaque id sent as X-Correlation-ID so backend log lines can be matched. */
export function newCorrelationId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** The login flow uses one id for the whole app session. */
export const loginCorrelationId = enabled ? newCorrelationId() : '';

export function perfLog(flow: PerfFlow, step: string, fields: Record<string, unknown> = {}): void {
  if (!enabled) return;
  console.log('[perf]', JSON.stringify({ flow, step, ...fields }));
}

/** Logs a login-flow step with the time since app start. */
export function perfLoginStep(step: string, fields: Record<string, unknown> = {}): void {
  if (!enabled) return;
  perfLog('login', step, { correlation_id: loginCorrelationId, since_app_start_ms: Date.now() - appStartedAt, ...fields });
}
