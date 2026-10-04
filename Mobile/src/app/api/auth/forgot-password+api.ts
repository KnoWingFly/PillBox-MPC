import { db } from '@/server/db';
import { sendPasswordResetOtp } from '@/server/email';
import { json, parseBody, route } from '@/server/http';
import { OTP_RESEND_COOLDOWN_MS, OTP_TTL_MS, generateOtpCode, hashOtp } from '@/server/otp';
import { forgotPasswordSchema } from '@/server/schemas';

// Always the same response so the endpoint cannot be used to discover registered emails.
const SENT = { message: 'OTP_SENT_TO_EMAIL' } as const;

export const POST = route(async (request) => {
  const body = await parseBody(request, forgotPasswordSchema);

  const user = await db.user.findUnique({ where: { email: body.email }, select: { id: true, email: true } });
  if (!user) return json(SENT);

  const recent = await db.passwordResetOtp.findFirst({
    where: { userId: user.id, createdAt: { gt: new Date(Date.now() - OTP_RESEND_COOLDOWN_MS) } },
    select: { id: true },
  });
  if (recent) return json(SENT);

  const code = generateOtpCode();
  const now = new Date();
  await db.$transaction([
    db.passwordResetOtp.updateMany({ where: { userId: user.id, consumedAt: null }, data: { consumedAt: now } }),
    db.passwordResetOtp.create({
      data: { userId: user.id, codeHash: await hashOtp(code), expiresAt: new Date(now.getTime() + OTP_TTL_MS) },
    }),
  ]);

  try {
    await sendPasswordResetOtp(user.email, code);
  } catch (err) {
    // Do not reveal delivery failures (that would also reveal the account exists).
    console.error('[api] failed to send password reset email', err);
  }
  return json(SENT);
});
