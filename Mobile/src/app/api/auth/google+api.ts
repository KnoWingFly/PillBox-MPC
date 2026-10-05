import type { User as SupabaseUser, UserIdentity } from '@supabase/supabase-js';

import { db } from '@/server/db';
import { HttpError, unauthorized } from '@/server/errors';
import { json, parseBody, route, userAgent } from '@/server/http';
import { googleSchema } from '@/server/schemas';
import { supabaseAdmin } from '@/server/supabase-admin';
import { issueTokens, toTokenResponse } from '@/server/tokens';
import { isUniqueViolation } from '@/server/users';

const invalidToken = () => unauthorized('GOOGLE_TOKEN_INVALID', 'Google sign-in token is invalid');

type GoogleProfile = {
  supabaseUserId: string;
  providerUserId: string;
  email: string;
  emailVerified: boolean;
  fullName: string;
};

// Shape per @supabase/auth-js `User`/`UserIdentity` types: identities[].provider === 'google',
// identity_data carries the Google OIDC claims (sub, email, email_verified, name/full_name).
function extractGoogleProfile(user: SupabaseUser): GoogleProfile | null {
  const identity: UserIdentity | undefined = user.identities?.find((i) => i.provider === 'google');
  if (!identity) return null;
  const data = identity.identity_data ?? {};

  const providerUserId = String(data.sub ?? data.provider_id ?? identity.id ?? '');
  const email = String(data.email ?? user.email ?? '').trim().toLowerCase();
  if (!providerUserId || !email) return null;

  const emailVerified =
    typeof data.email_verified === 'boolean' ? data.email_verified : Boolean(user.email_confirmed_at);
  const name = data.full_name ?? data.name ?? user.user_metadata?.full_name ?? user.user_metadata?.name;
  const fullName = (typeof name === 'string' && name.trim()) || email.split('@')[0];

  return { supabaseUserId: user.id, providerUserId, email, emailVerified, fullName: fullName.slice(0, 100) };
}

async function resolveUser(profile: GoogleProfile, timezone: string) {
  const identity = await db.authIdentity.findUnique({
    where: { provider_providerUserId: { provider: 'GOOGLE', providerUserId: profile.providerUserId } },
    include: { user: true },
  });
  if (identity) {
    if (!identity.supabaseUserId) {
      await db.authIdentity.update({ where: { id: identity.id }, data: { supabaseUserId: profile.supabaseUserId } });
    }
    return { user: identity.user, isNew: false };
  }

  const existing = await db.user.findUnique({ where: { email: profile.email } });
  if (existing) {
    // Only link to an existing email/password account when Google vouches for the email.
    if (!profile.emailVerified) {
      throw new HttpError(409, 'EMAIL_ALREADY_REGISTERED', 'Email is already registered');
    }
    await db.authIdentity.create({
      data: {
        userId: existing.id,
        provider: 'GOOGLE',
        providerUserId: profile.providerUserId,
        supabaseUserId: profile.supabaseUserId,
        email: profile.email,
      },
    });
    return { user: existing, isNew: false };
  }

  const user = await db.user.create({
    data: {
      fullName: profile.fullName,
      email: profile.email,
      passwordHash: null,
      phoneNumber: null,
      timezone,
      identities: {
        create: {
          provider: 'GOOGLE',
          providerUserId: profile.providerUserId,
          supabaseUserId: profile.supabaseUserId,
          email: profile.email,
        },
      },
    },
  });
  return { user, isNew: true };
}

export const POST = route(async (request) => {
  const body = await parseBody(request, googleSchema);

  const { data, error } = await supabaseAdmin().auth.getUser(body.supabase_access_token);
  if (error || !data.user) throw invalidToken();
  const profile = extractGoogleProfile(data.user);
  if (!profile) throw invalidToken();

  let resolved;
  try {
    resolved = await resolveUser(profile, body.timezone);
  } catch (err) {
    // A concurrent first sign-in created the same user/identity; the retry finds it.
    if (!isUniqueViolation(err)) throw err;
    resolved = await resolveUser(profile, body.timezone);
  }

  const { user, isNew } = resolved;
  const tokens = await issueTokens(user.id, { userAgent: userAgent(request) });
  return json({
    ...toTokenResponse(tokens),
    caregiver: { id: user.id, full_name: user.fullName, email: user.email, google_linked: true },
    is_new_account: isNew,
  });
});
