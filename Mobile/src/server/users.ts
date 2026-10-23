import { Prisma, type User } from '@prisma/client';

import { db } from './db';
import { unauthorized } from './errors';

function hasPrismaCode(err: unknown, code: string): boolean {
  return err instanceof Prisma.PrismaClientKnownRequestError && err.code === code;
}

export const isUniqueViolation = (err: unknown) => hasPrismaCode(err, 'P2002');
/** Write referenced a user that no longer exists (FK failed or record to update missing). */
export const isMissingUser = (err: unknown) => hasPrismaCode(err, 'P2003') || hasPrismaCode(err, 'P2025');

// Loads the authenticated user; a token for a deleted user is treated as invalid.
export async function getAuthedUser(userId: string) {
  const user = await db.user.findUnique({
    where: { id: userId },
    include: { identities: { select: { provider: true } } },
  });
  if (!user) throw unauthorized();
  return user;
}

export function toSettingResponse(user: User & { identities: { provider: string }[] }) {
  return {
    id: user.id,
    full_name: user.fullName,
    email: user.email,
    phone_number: user.phoneNumber,
    timezone: user.timezone,
    google_linked: user.identities.some((i) => i.provider === 'GOOGLE'),
    has_password: user.passwordHash !== null,
    interface_language: user.interfaceLanguage,
    display_mode: user.displayMode,
    created_at: user.createdAt.toISOString(),
  };
}
