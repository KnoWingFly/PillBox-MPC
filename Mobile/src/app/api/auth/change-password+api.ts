import { requireAuth } from '@/server/auth-guard';
import { db } from '@/server/db';
import { unauthorized } from '@/server/errors';
import { json, parseBody, route } from '@/server/http';
import { hashPassword, verifyPassword } from '@/server/passwords';
import { changePasswordSchema } from '@/server/schemas';
import { revokeAllForUser } from '@/server/tokens';

export const PUT = route(async (request) => {
  const { userId, familyId } = await requireAuth(request);
  const body = await parseBody(request, changePasswordSchema);
  const user = await db.user.findUnique({ where: { id: userId }, select: { passwordHash: true } });
  if (!user) throw unauthorized();

  // Google-only accounts have no password yet: this call sets the first one.
  if (user.passwordHash) {
    const ok = body.old_password !== undefined && (await verifyPassword(body.old_password, user.passwordHash));
    if (!ok) throw unauthorized('INVALID_OLD_PASSWORD', 'Old password is incorrect');
  }

  await db.user.update({ where: { id: userId }, data: { passwordHash: await hashPassword(body.new_password) } });
  // Sign out every other session; keep the one making this request.
  await revokeAllForUser(userId, { exceptFamilyId: familyId });
  return json({ message: 'PASSWORD_CHANGED_SUCCESS' });
});
