import { requireAuth } from '@/server/auth-guard';
import { db } from '@/server/db';
import { unauthorized } from '@/server/errors';
import { json, parseBody, route } from '@/server/http';
import { pushTokenSchema } from '@/server/schemas';
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

// Idempotent upsert by token; a token registered by another user moves to the current user
// (the device changed hands / signed into a different account).
export const POST = route(async (request) => {
  const { userId } = await requireAuth(request);
  const body = await parseBody(request, pushTokenSchema);

  const fields = { userId, platform: body.platform, deviceLabel: body.device_label ?? null, lastSeenAt: new Date() };
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
  return json({ id: token.id, platform: token.platform, created_at: token.createdAt.toISOString() });
});
