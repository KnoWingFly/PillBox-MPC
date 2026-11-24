// Shared by the app (src/lib/api) and the auth server (src/server): how the web app carries its
// refresh token (Mobile/BACKEND_HANDOFF.md item 9).
//
// On web the refresh token lives in an HttpOnly cookie that page scripts cannot read. The app asks
// for it with this request header; the server then sets the cookie and leaves `refresh_token` out
// of the JSON body. Native apps send no header and keep receiving the token in the body.

export const TOKEN_TRANSPORT_HEADER = 'X-Token-Transport';
export const TOKEN_TRANSPORT_COOKIE = 'cookie';

/**
 * What the web app stores in place of the refresh token it can no longer see: it only says "a
 * cookie session exists" (not a secret), so a reload knows to restore the session.
 */
export const COOKIE_SESSION_MARKER = 'httponly-cookie';
