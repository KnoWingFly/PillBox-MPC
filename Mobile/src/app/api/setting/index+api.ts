import { requireAuth } from '@/server/auth-guard';
import { db } from '@/server/db';
import { HttpError, unauthorized, validationError } from '@/server/errors';
import { json, noContent, parseBody, route } from '@/server/http';
import { verifyPassword } from '@/server/passwords';
import { deleteAccountSchema, updateSettingSchema } from '@/server/schemas';
import { supabaseAdmin } from '@/server/supabase-admin';
import { getAuthedUser, isMissingUser, toSettingResponse } from '@/server/users';

/**
 * Whether the user is OWNER of an elderly profile that is not deleted. Read-only query on two
 * Backend tables (user_elderly_roles, elderly); Prisma does not model them.
 */
async function ownsActiveElderly(userId: string): Promise<boolean> {
  const rows = await db.$queryRaw<{ found: number }[]>`
    SELECT 1 AS found
    FROM user_elderly_roles r
    JOIN elderly e ON e.id = r.elderly_id
    WHERE r.user_id = ${userId}::uuid AND r.role = 'OWNER' AND e.deleted_at IS NULL
    LIMIT 1`;
  return rows.length > 0;
}

export const GET = route(async (request) => {
  const { userId } = await requireAuth(request);
  return json(toSettingResponse(await getAuthedUser(userId)));
});

export const PUT = route(async (request) => {
  const { userId } = await requireAuth(request);
  const body = await parseBody(request, updateSettingSchema);

  try {
    const user = await db.user.update({
      where: { id: userId },
      data: {
        fullName: body.full_name,
        phoneNumber: body.phone_number,
        timezone: body.timezone,
        interfaceLanguage: body.interface_language,
        displayMode: body.display_mode,
      },
      include: { identities: { select: { provider: true } } },
    });
    return json(toSettingResponse(user));
  } catch (err) {
    if (isMissingUser(err)) throw unauthorized(); // token for a deleted user
    throw err;
  }
});

export const DELETE = route(async (request) => {
  const { userId } = await requireAuth(request);
  const body = await parseBody(request, deleteAccountSchema);
  const user = await db.user.findUnique({
    where: { id: userId },
    include: { identities: { select: { supabaseUserId: true } } },
  });
  if (!user) throw unauthorized();

  if (user.passwordHash) {
    if (body.password === undefined) throw validationError([{ path: 'password', message: 'Password is required' }]);
    if (!(await verifyPassword(body.password, user.passwordHash))) {
      throw unauthorized('INVALID_PASSWORD', 'Password is incorrect');
    }
  } else if (body.confirm !== 'DELETE') {
    throw validationError([{ path: 'confirm', message: 'Must be "DELETE"' }]);
  }

  // Deleting the user cascades its user_elderly_roles rows, which would leave an elderly profile
  // without an OWNER (docs/ai/architecture.md conflict 5): ownership must be transferred first.
  if (await ownsActiveElderly(userId)) {
    throw new HttpError(409, 'CANNOT_REMOVE_OWNER', 'Transfer ownership of your elderly profiles before deleting the account');
  }

  // Supabase first: if it fails we return 500 and the DB row stays untouched.
  const supabaseIds = [...new Set(user.identities.map((i) => i.supabaseUserId).filter((id) => id !== null))];
  for (const id of supabaseIds) {
    const { error } = await supabaseAdmin().auth.admin.deleteUser(id);
    // An already-deleted Supabase user is fine; anything else aborts.
    if (error && error.status !== 404) throw new Error(`Supabase deleteUser failed (status ${error.status})`);
  }

  await db.user.delete({ where: { id: userId } }); // cascades identities, tokens, OTPs, push tokens
  return noContent();
});
