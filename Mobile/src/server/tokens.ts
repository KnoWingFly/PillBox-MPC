import type { Prisma } from '@prisma/client';
import { SignJWT, jwtVerify } from 'jose';

import { serverConfig } from './config';
import { randomBytes, sha256Hex, toBase64Url } from './crypto';
import { db } from './db';
import { env } from './env';
import { unauthorized } from './errors';

export const ACCESS_TOKEN_TTL_SECONDS = 15 * 60;

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

type DbClient = Prisma.TransactionClient | typeof db;

/** A pair as issued, with what the HTTP layer needs that is not part of the response body. */
export type IssuedTokens = TokenResponse & { refreshTokenId: string; refreshExpiresAt: Date };

/** Session length for a new sign-in: "Ingat saya" off gets a short-lived refresh token. */
export function sessionTtlMs(remember: boolean): number {
  return remember ? serverConfig.refreshTokenTtlMs : serverConfig.refreshTokenShortTtlMs;
}

// Issues an access + refresh pair. Pass familyId to continue an existing family (rotation), and
// `client` to write inside a transaction. A new session lasts `ttlMs`; a rotation passes the old
// token's `expiresAt`, so a session ends a fixed time after sign-in however often it is refreshed.
export async function issueTokens(
  userId: string,
  opts: { familyId?: string; userAgent?: string | null; client?: DbClient; ttlMs?: number; expiresAt?: Date } = {},
): Promise<IssuedTokens> {
  const familyId = opts.familyId ?? crypto.randomUUID();
  const refreshToken = newRefreshToken();
  const expiresAt = opts.expiresAt ?? new Date(Date.now() + (opts.ttlMs ?? serverConfig.refreshTokenTtlMs));
  const row = await (opts.client ?? db).refreshToken.create({
    data: {
      userId,
      familyId,
      tokenHash: await sha256Hex(refreshToken),
      expiresAt,
      userAgent: opts.userAgent ?? null,
    },
  });
  return {
    access_token: await signAccessToken(userId, familyId),
    refresh_token: refreshToken,
    token_type: 'Bearer',
    expires_in: ACCESS_TOKEN_TTL_SECONDS,
    refreshTokenId: row.id,
    refreshExpiresAt: expiresAt,
  };
}

export function toTokenResponse({ refreshTokenId: _id, refreshExpiresAt: _exp, ...tokens }: IssuedTokens): TokenResponse {
  return tokens;
}

/** Ends a session. Push tokens registered under it stop receiving alerts too. */
export async function revokeFamily(familyId: string): Promise<void> {
  await db.refreshToken.updateMany({ where: { familyId, revokedAt: null }, data: { revokedAt: new Date() } });
  await db.pushToken.deleteMany({ where: { refreshFamilyId: familyId } });
}

/**
 * Deletes the user's push tokens whose session ended without a logout (app killed with "Ingat saya"
 * off, the 30-day cap, revoked elsewhere), so a phone nobody is signed in on gets no medication
 * alerts. Tokens from before sessions were recorded (no family) are left alone.
 */
export async function pruneEndedSessionPushTokens(userId: string): Promise<void> {
  const tokens = await db.pushToken.findMany({
    where: { userId, refreshFamilyId: { not: null } },
    select: { id: true, refreshFamilyId: true },
  });
  if (tokens.length === 0) return;
  const families = [...new Set(tokens.map((t) => t.refreshFamilyId as string))];
  const live = await db.refreshToken.findMany({
    where: { familyId: { in: families }, revokedAt: null, expiresAt: { gt: new Date() } },
    select: { familyId: true },
    distinct: ['familyId'],
  });
  const liveFamilies = new Set(live.map((r) => r.familyId));
  const ended = tokens.filter((t) => !liveFamilies.has(t.refreshFamilyId as string)).map((t) => t.id);
  if (ended.length > 0) await db.pushToken.deleteMany({ where: { id: { in: ended } } });
}

export async function revokeAllForUser(userId: string, opts: { exceptFamilyId?: string } = {}): Promise<void> {
  const except = opts.exceptFamilyId ? { familyId: { not: opts.exceptFamilyId } } : {};
  await db.refreshToken.updateMany({ where: { userId, revokedAt: null, ...except }, data: { revokedAt: new Date() } });
  // Phones of the ended sessions stop receiving alerts (the kept session's phone keeps its token).
  await db.pushToken.deleteMany({
    where: {
      userId,
      refreshFamilyId: opts.exceptFamilyId ? { not: null, notIn: [opts.exceptFamilyId] } : { not: null },
    },
  });
}

/** Rotations a grace-window replay may follow (two tabs plus a retry); more looks like abuse. */
const MAX_GRACE_HOPS = 3;

type RotateOutcome = { ok: IssuedTokens } | { revokeFamily: string } | { invalid: true; endedFamily?: string };

/** Claims `id` (marks it rotated) and chains a new token to it. null = someone else claimed it first. */
async function claimAndIssue(
  tx: Prisma.TransactionClient,
  row: { id: string; userId: string; familyId: string; expiresAt: Date },
  userAgent: string | null,
): Promise<IssuedTokens | null> {
  const claimed = await tx.refreshToken.updateMany({
    where: { id: row.id, revokedAt: null, replacedById: null },
    data: { revokedAt: new Date() },
  });
  if (claimed.count !== 1) return null;
  // Same expiry as the token it replaces: the session ends a fixed time after sign-in.
  const next = await issueTokens(row.userId, { familyId: row.familyId, userAgent, client: tx, expiresAt: row.expiresAt });
  await tx.refreshToken.update({ where: { id: row.id }, data: { replacedById: next.refreshTokenId } });
  return next;
}

// Rotates a refresh token in one transaction (claim, insert, link), so a crash or a lost
// connection can never leave a claimed token without its replacement.
// Presenting an already-rotated token is treated as theft and revokes the whole family, except
// within serverConfig.refreshReuseGraceMs of the rotation while its replacement is still unused:
// that is a retry after a lost response (or two tabs refreshing together), and gets a fresh pair
// chained after the unused replacement.
export async function rotateRefreshToken(refreshToken: string, userAgent: string | null): Promise<IssuedTokens> {
  const invalid = () => unauthorized('REFRESH_TOKEN_INVALID', 'Refresh token is invalid or expired');
  const tokenHash = await sha256Hex(refreshToken);

  const outcome = await db.$transaction(async (tx): Promise<RotateOutcome> => {
    const existing = await tx.refreshToken.findUnique({ where: { tokenHash } });
    if (!existing) return { invalid: true };
    // Past the session's end (30 days, or the short "Ingat saya" off session): signed out.
    if (existing.expiresAt.getTime() <= Date.now()) return { invalid: true, endedFamily: existing.familyId };

    if (!existing.revokedAt && !existing.replacedById) {
      const rotated = await claimAndIssue(tx, existing, userAgent);
      if (rotated) return { ok: rotated };
    }

    // Already rotated (or a concurrent request rotated it just now): follow the chain of
    // replacements made within the grace window to the newest unused token and rotate that.
    // Re-reads see what concurrent requests committed meanwhile (READ COMMITTED).
    let cursor = await tx.refreshToken.findUnique({ where: { id: existing.id } });
    for (let hop = 0; hop < MAX_GRACE_HOPS && cursor?.replacedById; hop += 1) {
      if (Date.now() - (cursor.revokedAt?.getTime() ?? 0) > serverConfig.refreshReuseGraceMs) break;
      const next = await tx.refreshToken.findUnique({ where: { id: cursor.replacedById } });
      if (!next || next.expiresAt.getTime() <= Date.now()) break;
      if (!next.revokedAt && !next.replacedById) {
        const retried = await claimAndIssue(tx, next, userAgent);
        if (retried) return { ok: retried };
        cursor = await tx.refreshToken.findUnique({ where: { id: next.id } }); // rotated concurrently: follow it
      } else cursor = next;
    }
    return { revokeFamily: existing.familyId };
  });

  if ('ok' in outcome) return outcome.ok;
  // Outside the transaction: an error thrown inside it would roll the revocation back.
  if ('revokeFamily' in outcome) await revokeFamily(outcome.revokeFamily);
  if ('endedFamily' in outcome && outcome.endedFamily) {
    await db.pushToken.deleteMany({ where: { refreshFamilyId: outcome.endedFamily } });
  }
  throw invalid();
}

/** When the session (refresh-token family) began, i.e. the interactive sign-in; null if unknown. */
export async function familyStartedAt(familyId: string): Promise<Date | null> {
  const first = await db.refreshToken.findFirst({
    where: { familyId },
    orderBy: { createdAt: 'asc' },
    select: { createdAt: true },
  });
  return first?.createdAt ?? null;
}

/** True when the user still has a refresh token that is neither revoked nor expired. */
export async function hasLiveSession(userId: string): Promise<boolean> {
  const live = await db.refreshToken.findFirst({
    where: { userId, revokedAt: null, expiresAt: { gt: new Date() } },
    select: { id: true },
  });
  return live !== null;
}

// Looks up a refresh token's family without validating it (used by logout).
export async function findFamilyId(refreshToken: string): Promise<string | null> {
  const row = await db.refreshToken.findUnique({
    where: { tokenHash: await sha256Hex(refreshToken) },
    select: { familyId: true },
  });
  return row?.familyId ?? null;
}
