import { requireAuth } from '@/server/auth-guard';
import { db } from '@/server/db';
import { forbidden, unauthorized } from '@/server/errors';
import { json, parseBody, route } from '@/server/http';
import { pushTokenSchema } from '@/server/schemas';
import { hasLiveSession, pruneEndedSessionPushTokens } from '@/server/tokens';
import { isMissingUser } from '@/server/users';

export const GET = route(async (request) => {
  const { userId } = await requireAuth(request);
  const tokens = await db.pushToken.findMany({ where: { userId }, orderBy: { createdAt: 'desc' } });
  return json(
    tokens.map((t) => ({
      id: t.id,
      platform: t.platform,
      device_label: t.deviceLabel,
      created_at: t.createdAt.toISOString(),
    })),
  );
});

// Idempotent upsert by token. A token registered to ANOTHER user is not taken over while that user
// still has a live session: otherwise anyone who learned a caregiver's push token could redirect
// their medication alerts. Logout deletes the token (src/lib/push-token.ts), so a phone that changes
// accounts normally finds it free; a token whose owner has no live session left is moved.
export const POST = route(async (request) => {
  const { userId, familyId } = await requireAuth(request);
  const body = await parseBody(request, pushTokenSchema);

  const current = await db.pushToken.findUnique({ where: { token: body.token }, select: { userId: true } });
  if (current && current.userId !== userId && (await hasLiveSession(current.userId))) {
    throw forbidden('This push token belongs to another signed-in account');
  }

  // The session it belongs to: logout or the end of that session deletes it (src/server/tokens.ts).
  const fields = {
    userId,
    refreshFamilyId: familyId,
    platform: body.platform,
    deviceLabel: body.device_label ?? null,
    lastSeenAt: new Date(),
  };
  let token;
  try {
    token = await db.pushToken.upsert({
      where: { token: body.token },
      create: { token: body.token, ...fields },
      update: fields,
    });
  } catch (err) {
    if (isMissingUser(err)) throw unauthorized(); // token for a deleted user
    throw err;
  }
  await pruneEndedSessionPushTokens(userId);
  return json({ id: token.id, platform: token.platform, created_at: token.createdAt.toISOString() });
});
