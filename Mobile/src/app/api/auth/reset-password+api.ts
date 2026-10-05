import { db } from '@/server/db';
import { HttpError } from '@/server/errors';
import { json, parseBody, route } from '@/server/http';
import { OTP_MAX_ATTEMPTS, hashOtp, otpMatches } from '@/server/otp';
import { hashPassword } from '@/server/passwords';
import { resetPasswordSchema } from '@/server/schemas';
import { revokeAllForUser } from '@/server/tokens';

// Identical for unknown email, missing/expired/wrong/exhausted OTP.
const invalidOtp = () => new HttpError(400, 'INVALID_OTP', 'OTP code is invalid or expired');

export const POST = route(async (request) => {
  const body = await parseBody(request, resetPasswordSchema);

  const user = await db.user.findUnique({ where: { email: body.email }, select: { id: true } });
  const otp = user
    ? await db.passwordResetOtp.findFirst({
        where: { userId: user.id, consumedAt: null, expiresAt: { gt: new Date() } },
        orderBy: { createdAt: 'desc' },
      })
    : null;

  if (!user || !otp) {
    await hashOtp(body.otp_code); // keep work comparable to the real path
    throw invalidOtp();
  }

  // Count the attempt atomically before checking, so parallel guesses cannot exceed the limit.
  const counted = await db.passwordResetOtp.updateMany({
    where: { id: otp.id, consumedAt: null, attempts: { lt: OTP_MAX_ATTEMPTS } },
    data: { attempts: { increment: 1 } },
  });
  if (counted.count !== 1) {
    await db.passwordResetOtp.update({ where: { id: otp.id }, data: { consumedAt: new Date() } });
    throw invalidOtp();
  }

  if (!(await otpMatches(body.otp_code, otp.codeHash))) {
    if (otp.attempts + 1 >= OTP_MAX_ATTEMPTS) {
      await db.passwordResetOtp.update({ where: { id: otp.id }, data: { consumedAt: new Date() } });
    }
    throw invalidOtp();
  }

  // Consume first; if another request consumed it concurrently, this one fails.
  const consumed = await db.passwordResetOtp.updateMany({
    where: { id: otp.id, consumedAt: null },
    data: { consumedAt: new Date() },
  });
  if (consumed.count !== 1) throw invalidOtp();

  await db.user.update({ where: { id: user.id }, data: { passwordHash: await hashPassword(body.new_password) } });
  await revokeAllForUser(user.id);
  return json({ message: 'PASSWORD_RESET_SUCCESS' });
});
