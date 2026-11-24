import { HttpError } from '@/server/errors';
import { parseBody, route, userAgent } from '@/server/http';
import { timed } from '@/server/perf';
import { refreshSchema } from '@/server/schemas';
import { clearSessionCookie, refreshTokenOf, sessionResponse } from '@/server/session-cookie';
import { rotateRefreshToken } from '@/server/tokens';

// The refresh token comes in the body (native) or the HttpOnly cookie (web, src/server/session-cookie.ts).
export const POST = route(async (request) => {
  const body = await parseBody(request, refreshSchema);
  const refreshToken = refreshTokenOf(request, body.refresh_token);
  try {
    if (!refreshToken) throw new HttpError(401, 'REFRESH_TOKEN_INVALID', 'Refresh token is invalid or expired');
    // One transaction: find, claim, insert, link (see tokens.ts).
    const issued = await timed(request, 'rotate_refresh_token', () => rotateRefreshToken(refreshToken, userAgent(request)));
    return sessionResponse(request, issued);
  } catch (err) {
    // A rejected session also drops the web cookie, so the browser stops sending a dead token.
    if (err instanceof HttpError && err.status === 401) {
      return clearSessionCookie(
        request,
        Response.json({ error: { code: err.code, message: err.message } }, { status: err.status }),
      );
    }
    throw err;
  }
});
