import { db } from '@/server/db';
import { HttpError } from '@/server/errors';
import { json, parseBody, route, userAgent } from '@/server/http';
import { hashPassword } from '@/server/passwords';
import { registerSchema } from '@/server/schemas';
import { issueTokens, toTokenResponse } from '@/server/tokens';
import { isUniqueViolation } from '@/server/users';

const emailTaken = () => new HttpError(409, 'EMAIL_ALREADY_REGISTERED', 'Email is already registered');

export const POST = route(async (request) => {
  const body = await parseBody(request, registerSchema);

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

  const tokens = await issueTokens(user.id, { userAgent: userAgent(request) });
  return json(
    {
      ...toTokenResponse(tokens),
      caregiver: { id: user.id, full_name: user.fullName, created_at: user.createdAt.toISOString() },
    },
    201,
  );
});
