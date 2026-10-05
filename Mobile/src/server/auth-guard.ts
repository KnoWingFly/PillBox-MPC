import { unauthorized } from './errors';
import { verifyAccessToken, type AccessClaims } from './tokens';

// Requires `Authorization: Bearer <access_token>` issued by OUR server.
export async function requireAuth(request: Request): Promise<AccessClaims> {
  const header = request.headers.get('authorization');
  const match = header?.match(/^Bearer\s+(.+)$/i);
  if (!match) throw unauthorized();
  return verifyAccessToken(match[1].trim());
}
