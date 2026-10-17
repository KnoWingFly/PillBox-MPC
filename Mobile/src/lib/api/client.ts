import Constants from 'expo-constants';
import { Platform } from 'react-native';

import { AppConfig } from '@/config';
import { loginCorrelationId, perfEnabled, perfLoginStep } from '@/lib/perf';

import { tokenStore } from './token-store';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: 'Bearer';
  expires_in: number;
};

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  /** Attach the bearer token and retry once after a refresh on 401. Default true. */
  auth?: boolean;
};

function baseUrl(): string {
  if (AppConfig.apiUrl) return AppConfig.apiUrl;
  if (Platform.OS === 'web') return ''; // same origin as the dev server
  // In development the API routes are served by the same dev server that serves the JS bundle,
  // so reuse its address (e.g. "192.168.1.10:8081"). Only present when running via `expo start`.
  const hostUri = Constants.expoConfig?.hostUri;
  if (__DEV__ && hostUri) return `http://${hostUri}`;
  throw new ApiError(0, 'NETWORK_ERROR', 'EXPO_PUBLIC_API_URL is not set');
}

// ---- session-expired signal (consumed by the auth provider) ----
type Listener = () => void;
const sessionExpiredListeners = new Set<Listener>();
export function onSessionExpired(listener: Listener): () => void {
  sessionExpiredListeners.add(listener);
  return () => sessionExpiredListeners.delete(listener);
}

/**
 * fetch() with a deadline. React Native's fetch has no default timeout, so an unreachable host
 * (stale LAN IP, Wi-Fi switching networks) can otherwise hang a request, and the splash screen
 * that waits on it, until the OS gives up. A timeout is reported as NETWORK_ERROR so callers keep
 * their existing offline handling (e.g. session restore keeps the session).
 */
export async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs = AppConfig.requestTimeoutMs): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', controller.signal.aborted ? 'Request timed out' : 'Network request failed');
  } finally {
    clearTimeout(timer);
  }
}

let firstCallLogged = false;

async function send(path: string, opts: RequestOptions, accessToken: string | null): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (perfEnabled()) {
    headers['X-Correlation-ID'] = loginCorrelationId;
    if (!firstCallLogged) {
      firstCallLogged = true;
      perfLoginStep('first_api_call_sent', { path });
    }
  }
  return fetchWithTimeout(`${baseUrl()}${path}`, {
    method: opts.method ?? 'GET',
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
}

async function toApiError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    if (body?.error?.code) return new ApiError(res.status, body.error.code, body.error.message, body.error.details);
  } catch {
    // non-JSON error body
  }
  return new ApiError(res.status, 'INTERNAL_ERROR', `Request failed with status ${res.status}`);
}

// ---- single-flight refresh: concurrent 401s share one refresh request ----
let refreshInFlight: Promise<string | null> | null = null;

async function doRefresh(): Promise<string | null> {
  const refreshToken = await tokenStore.getRefreshToken();
  if (!refreshToken) return null;
  const res = await send('/api/auth/refresh', { method: 'POST', body: { refresh_token: refreshToken } }, null);
  if (!res.ok) {
    if (res.status === 401) return null; // refresh token rejected: session is over
    throw await toApiError(res);
  }
  const tokens = (await res.json()) as TokenResponse;
  await tokenStore.setTokens(tokens.access_token, tokens.refresh_token);
  return tokens.access_token;
}

/** Rotates the token pair (single-flight). Resolves null when the refresh token was rejected. */
export function refreshAccessToken(): Promise<string | null> {
  refreshInFlight ??= doRefresh().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

export async function expireSession(): Promise<void> {
  await tokenStore.clear();
  sessionExpiredListeners.forEach((listener) => listener());
}

/** `exp` of a JWT in epoch ms, read without verifying (the server verifies). null if unreadable. */
export function tokenExpiresAtMs(token: string): number | null {
  try {
    const payload = token.split('.')[1];
    if (!payload || typeof atob !== 'function') return null;
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(payload.length / 4) * 4, '=');
    const exp = (JSON.parse(atob(base64)) as { exp?: unknown }).exp;
    return typeof exp === 'number' ? exp * 1000 : null;
  } catch {
    return null;
  }
}

/**
 * The stored access token, refreshed first if it has (nearly) expired. Access tokens live 15 minutes,
 * so after a pause the first request would otherwise make a guaranteed-401 round trip before the
 * refresh. Throws UNAUTHORIZED (and ends the session) when the refresh token is rejected.
 */
export async function getFreshAccessToken(): Promise<string | null> {
  const token = await tokenStore.getAccessToken();
  if (!token) return null;
  const expiresAt = tokenExpiresAtMs(token);
  if (expiresAt === null || expiresAt - AppConfig.tokenRefreshSkewMs > Date.now()) return token;
  const fresh = await refreshAccessToken();
  if (!fresh) {
    await expireSession();
    throw new ApiError(401, 'UNAUTHORIZED', 'Session expired');
  }
  return fresh;
}

export async function apiFetch<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const useAuth = opts.auth ?? true;
  let res = await send(path, opts, useAuth ? await getFreshAccessToken() : null);

  // Only an invalid/expired access token (UNAUTHORIZED) triggers a refresh. Other 401s such as
  // INVALID_OLD_PASSWORD are ordinary errors and must not end the session.
  if (res.status === 401 && useAuth) {
    const err = await toApiError(res);
    if (err.code !== 'UNAUTHORIZED') throw err;

    const newAccessToken = await refreshAccessToken();
    if (!newAccessToken) {
      await expireSession();
      throw err;
    }
    res = await send(path, opts, newAccessToken);
    if (res.status === 401) {
      const retryErr = await toApiError(res);
      if (retryErr.code === 'UNAUTHORIZED') await expireSession();
      throw retryErr;
    }
  }

  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
