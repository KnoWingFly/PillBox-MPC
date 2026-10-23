import { SignJWT, jwtVerify } from 'jose';

import { randomBytes, sha256Hex, toBase64Url } from './crypto';
import { db } from './db';
import { env } from './env';
import { unauthorized } from './errors';

export const ACCESS_TOKEN_TTL_SECONDS = 15 * 60;
const REFRESH_TOKEN_TTL_MS = 30 * 24 * 60 * 60 * 1000;

export type AccessClaims = { userId: string; familyId: string };

export type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: 'Bearer';
  expires_in: number;
};

function accessKey(): Uint8Array {
  return new TextEncoder().encode(env.jwtAccessSecret);
}

export async function signAccessToken(userId: string, familyId: string): Promise<string> {
  return new SignJWT({ fid: familyId })
    .setProtectedHeader({ alg: 'HS256', typ: 'JWT' })
    .setSubject(userId)
    .setIssuedAt()
    .setExpirationTime(`${ACCESS_TOKEN_TTL_SECONDS}s`)
    .sign(accessKey());
}

export async function verifyAccessToken(token: string): Promise<AccessClaims> {
  const key = accessKey(); // outside try: a missing secret is a server error, not a 401
  try {
    const { payload } = await jwtVerify(token, key, { algorithms: ['HS256'] });
    if (typeof payload.sub !== 'string' || typeof payload.fid !== 'string') throw new Error('bad claims');
    return { userId: payload.sub, familyId: payload.fid };
  } catch {
    throw unauthorized();
  }
}

function newRefreshToken(): string {
  return toBase64Url(randomBytes(32));
}

// Issues an access + refresh pair. Pass familyId to continue an existing family (rotation).
export async function issueTokens(
  userId: string,
  opts: { familyId?: string; userAgent?: string | null } = {},
): Promise<TokenResponse & { refreshTokenId: string }> {
  const familyId = opts.familyId ?? crypto.randomUUID();
  const refreshToken = newRefreshToken();
  const row = await db.refreshToken.create({
    data: {
      userId,
      familyId,
      tokenHash: await sha256Hex(refreshToken),
      expiresAt: new Date(Date.now() + REFRESH_TOKEN_TTL_MS),
      userAgent: opts.userAgent ?? null,
    },
  });
  return {
    access_token: await signAccessToken(userId, familyId),
    refresh_token: refreshToken,
    token_type: 'Bearer',
    expires_in: ACCESS_TOKEN_TTL_SECONDS,
    refreshTokenId: row.id,
  };
}

export function toTokenResponse({ refreshTokenId: _id, ...tokens }: TokenResponse & { refreshTokenId: string }) {
  return tokens;
}

export async function revokeFamily(familyId: string): Promise<void> {
  await db.refreshToken.updateMany({ where: { familyId, revokedAt: null }, data: { revokedAt: new Date() } });
}

export async function revokeAllForUser(userId: string, opts: { exceptFamilyId?: string } = {}): Promise<void> {
  await db.refreshToken.updateMany({
    where: {
      userId,
      revokedAt: null,
      ...(opts.exceptFamilyId ? { familyId: { not: opts.exceptFamilyId } } : {}),
    },
    data: { revokedAt: new Date() },
  });
}

// Rotates a refresh token. Presenting an already-rotated or revoked token is treated
// as theft: the whole family is revoked.
export async function rotateRefreshToken(refreshToken: string, userAgent: string | null): Promise<TokenResponse> {
  const invalid = () => unauthorized('REFRESH_TOKEN_INVALID', 'Refresh token is invalid or expired');
  const existing = await db.refreshToken.findUnique({ where: { tokenHash: await sha256Hex(refreshToken) } });
  if (!existing) throw invalid();

  if (existing.revokedAt || existing.replacedById) {
    await revokeFamily(existing.familyId);
    throw invalid();
  }
  if (existing.expiresAt.getTime() <= Date.now()) throw invalid();

  // Atomically claim the token; a concurrent rotation of the same token loses here
  // and is treated as reuse.
  const claimed = await db.refreshToken.updateMany({
    where: { id: existing.id, revokedAt: null, replacedById: null },
    data: { revokedAt: new Date() },
  });
  if (claimed.count !== 1) {
    await revokeFamily(existing.familyId);
    throw invalid();
  }

  const next = await issueTokens(existing.userId, { familyId: existing.familyId, userAgent });
  await db.refreshToken.update({ where: { id: existing.id }, data: { replacedById: next.refreshTokenId } });
  return toTokenResponse(next);
}

// Looks up a refresh token's family without validating it (used by logout).
export async function findFamilyId(refreshToken: string): Promise<string | null> {
  const row = await db.refreshToken.findUnique({
    where: { tokenHash: await sha256Hex(refreshToken) },
    select: { familyId: true },
  });
  return row?.familyId ?? null;
}
