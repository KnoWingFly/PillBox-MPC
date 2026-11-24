// The web app's refresh token travels in an HttpOnly cookie instead of the JSON body, so a script
// injected into the page (XSS) cannot read it (Mobile/BACKEND_HANDOFF.md item 9). The app opts in
// per request with TOKEN_TRANSPORT_HEADER; native apps never send it and keep the token in the body
// (SecureStore). The cookie is scoped to /api/auth, so it reaches only login, refresh and logout.
import { COOKIE_SESSION_MARKER, TOKEN_TRANSPORT_COOKIE, TOKEN_TRANSPORT_HEADER } from '@/constants/auth';

import { serverConfig } from './config';
import { json } from './http';
import { toTokenResponse, type IssuedTokens } from './tokens';

const { name: COOKIE_NAME, path: COOKIE_PATH } = serverConfig.refreshCookie;

export function usesCookie(request: Request): boolean {
  return request.headers.get(TOKEN_TRANSPORT_HEADER)?.toLowerCase() === TOKEN_TRANSPORT_COOKIE;
}

/** The refresh token from the body, else from the cookie. The marker is never a token. */
export function refreshTokenOf(request: Request, fromBody: string | undefined): string | null {
  if (fromBody && fromBody !== COOKIE_SESSION_MARKER) return fromBody;
  const header = request.headers.get('cookie') ?? '';
  for (const part of header.split(';')) {
    const [key, ...rest] = part.trim().split('=');
    if (key === COOKIE_NAME) return decodeURIComponent(rest.join('=')) || null;
  }
  return null;
}

/** Secure everywhere but plain-http development (a Secure cookie would not be stored there). */
function isSecure(request: Request): boolean {
  const forwarded = request.headers.get('x-forwarded-proto');
  return (forwarded ?? new URL(request.url).protocol.replace(':', '')) === 'https';
}

function cookie(request: Request, value: string, maxAgeSeconds: number | null): string {
  const parts = [
    `${COOKIE_NAME}=${encodeURIComponent(value)}`,
    `Path=${COOKIE_PATH}`,
    'HttpOnly',
    'SameSite=Strict',
  ];
  if (isSecure(request)) parts.push('Secure');
  if (maxAgeSeconds !== null) parts.push(`Max-Age=${maxAgeSeconds}`);
  return parts.join('; ');
}

/**
 * The token response for login, register, Google sign-in and refresh. With cookie transport the
 * refresh token goes into the cookie and is left out of the body. A session longer than a short
 * one survives browser restarts (Max-Age); a short ("Ingat saya" off) one is a browser-session
 * cookie that ends when the browser closes.
 */
export function sessionResponse(request: Request, issued: IssuedTokens, extra: Record<string, unknown> = {}, status = 200): Response {
  const tokens = toTokenResponse(issued);
  if (!usesCookie(request)) return json({ ...tokens, ...extra }, status);
  const { refresh_token: refreshToken, ...withoutRefresh } = tokens;
  const remainingMs = issued.refreshExpiresAt.getTime() - Date.now();
  const persistent = remainingMs > serverConfig.refreshTokenShortTtlMs;
  const res = json({ ...withoutRefresh, ...extra }, status);
  res.headers.append('Set-Cookie', cookie(request, refreshToken, persistent ? Math.floor(remainingMs / 1000) : null));
  return res;
}

/** Removes the cookie (logout, rejected refresh). */
export function clearSessionCookie(request: Request, res: Response): Response {
  if (usesCookie(request) || refreshTokenOf(request, undefined)) res.headers.append('Set-Cookie', cookie(request, '', 0));
  return res;
}
