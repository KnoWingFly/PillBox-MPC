import { noContent, route } from '@/server/http';
import { refreshSchema } from '@/server/schemas';
import { clearSessionCookie, refreshTokenOf } from '@/server/session-cookie';
import { findFamilyId, revokeFamily } from '@/server/tokens';

// Public: the refresh token (body, or the web app's HttpOnly cookie) is the credential, so an
// expired access token never blocks logout. Idempotent: always 204, even for malformed, unknown or
// already-revoked tokens. Revoking the session also deletes the push tokens registered under it.
export const POST = route(async (request) => {
  let raw: unknown = {};
  try {
    const text = await request.text();
    raw = text ? JSON.parse(text) : {};
  } catch {
    raw = {};
  }
  const parsed = refreshSchema.safeParse(raw);
  const refreshToken = refreshTokenOf(request, parsed.success ? parsed.data.refresh_token : undefined);
  if (refreshToken) {
    const familyId = await findFamilyId(refreshToken);
    if (familyId) await revokeFamily(familyId);
  }
  return clearSessionCookie(request, noContent());
});
