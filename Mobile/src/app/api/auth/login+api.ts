import { db } from '@/server/db';
import { unauthorized } from '@/server/errors';
import { json, parseBody, route, userAgent } from '@/server/http';
import { verifyPasswordOrDummy } from '@/server/passwords';
import { loginSchema } from '@/server/schemas';
import { timed } from '@/server/perf';
import { issueTokens, toTokenResponse } from '@/server/tokens';

export const POST = route(async (request) => {
  const body = await parseBody(request, loginSchema);

  const user = await timed(request, 'user_lookup', () => db.user.findUnique({ where: { email: body.email } }));
  // Unknown email and Google-only accounts compare against a dummy hash: same timing, same error.
  const ok = await timed(request, 'bcrypt_compare', () => verifyPasswordOrDummy(body.password, user?.passwordHash));
  if (!user || !ok) throw unauthorized('INVALID_CREDENTIALS', 'Email or password is incorrect');

  const tokens = await timed(request, 'issue_tokens', () => issueTokens(user.id, { userAgent: userAgent(request) }));
  return json({ ...toTokenResponse(tokens), caregiver: { id: user.id, full_name: user.fullName } });
});
