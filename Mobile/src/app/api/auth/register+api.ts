import { serverConfig } from '@/server/config';
import { db } from '@/server/db';
import { HttpError } from '@/server/errors';
import { clientIp, parseBody, route, userAgent } from '@/server/http';
import { hashPassword } from '@/server/passwords';
import { consumeAttempt } from '@/server/rate-limit';
import { registerSchema } from '@/server/schemas';
import { sessionResponse } from '@/server/session-cookie';
import { issueTokens } from '@/server/tokens';
import { isUniqueViolation } from '@/server/users';

const emailTaken = () => new HttpError(409, 'EMAIL_ALREADY_REGISTERED', 'Email is already registered');

export const POST = route(async (request) => {
  const body = await parseBody(request, registerSchema);
  await consumeAttempt('register:ip', clientIp(request), serverConfig.limits.registerPerIp);

  // No pre-check query: the unique index on email is the source of truth (saves a round trip).
  let user;
  try {
    user = await db.user.create({
      data: {
        fullName: body.full_name,
        email: body.email,
        phoneNumber: body.phone_number,
        passwordHash: await hashPassword(body.password),
        timezone: body.timezone,
      },
    });
  } catch (err) {
    if (isUniqueViolation(err)) throw emailTaken();
    throw err;
  }

  // A new account is remembered: sign-up has no "Ingat saya" choice.
  const tokens = await issueTokens(user.id, { userAgent: userAgent(request) });
  return sessionResponse(
    request,
    tokens,
    { caregiver: { id: user.id, full_name: user.fullName, created_at: user.createdAt.toISOString() } },
    201,
  );
});
