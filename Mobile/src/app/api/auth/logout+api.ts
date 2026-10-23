import { noContent, route } from '@/server/http';
import { refreshSchema } from '@/server/schemas';
import { findFamilyId, revokeFamily } from '@/server/tokens';

// Public: the refresh token is the credential, so an expired access token never blocks logout.
// Idempotent: always 204, even for malformed, unknown or already-revoked tokens.
export const POST = route(async (request) => {
  let raw: unknown = {};
  try {
    raw = await request.json();
  } catch {
    return noContent();
  }
  const parsed = refreshSchema.safeParse(raw);
  if (!parsed.success) return noContent();

  const familyId = await findFamilyId(parsed.data.refresh_token);
  if (familyId) await revokeFamily(familyId);
  return noContent();
});
