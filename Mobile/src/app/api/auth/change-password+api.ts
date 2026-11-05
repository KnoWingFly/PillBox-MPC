import { requireAuth } from '@/server/auth-guard';
import { db } from '@/server/db';
import { serverConfig } from '@/server/config';
import { forbidden, unauthorized } from '@/server/errors';
import { json, parseBody, route } from '@/server/http';
import { hashPassword, verifyPassword } from '@/server/passwords';
import { changePasswordSchema } from '@/server/schemas';
import { familyStartedAt, revokeAllForUser } from '@/server/tokens';

export const PUT = route(async (request) => {
  const { userId, familyId } = await requireAuth(request);
  const body = await parseBody(request, changePasswordSchema);
  const user = await db.user.findUnique({ where: { id: userId }, select: { passwordHash: true } });
  if (!user) throw unauthorized();

  if (user.passwordHash) {
    const ok = body.old_password !== undefined && (await verifyPassword(body.old_password, user.passwordHash));
    if (!ok) throw unauthorized('INVALID_OLD_PASSWORD', 'Old password is incorrect');
  } else {
    // Google-only account setting its first password: there is no old password to prove who is
    // asking, so require a fresh Google sign-in (this session started within the re-auth window).
    // A stolen long-lived session cannot add a password this way. The OTP flow
    // (forgot-password -> reset-password) remains the alternative.
    const startedAt = await familyStartedAt(familyId);
    if (startedAt === null || Date.now() - startedAt.getTime() > serverConfig.passwordReauthWindowMs) {
      throw forbidden('Sign in with Google again before setting a password');
    }
  }

  await db.user.update({ where: { id: userId }, data: { passwordHash: await hashPassword(body.new_password) } });
  // Sign out every other session; keep the one making this request.
  await revokeAllForUser(userId, { exceptFamilyId: familyId });
  return json({ message: 'PASSWORD_CHANGED_SUCCESS' });
});
