import { requireAuth } from '@/server/auth-guard';
import { db } from '@/server/db';
import { notFound } from '@/server/errors';
import { noContent, route } from '@/server/http';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const DELETE = route<{ push_token_id: string }>(async (request, { push_token_id }) => {
  const { userId } = await requireAuth(request);
  if (!UUID.test(push_token_id)) throw notFound();

  // Scoped by owner: another user's token id is indistinguishable from a missing one.
  const { count } = await db.pushToken.deleteMany({ where: { id: push_token_id, userId } });
  if (count === 0) throw notFound();
  return noContent();
});
