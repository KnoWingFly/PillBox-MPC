import bcrypt from 'bcryptjs';

// bcryptjs is pure JS: cost 12 measured ~740 ms/compare locally, cost 10 ~200 ms. Using 10 (the
// spec's allowed minimum) to keep login/register responsive. Hashes made at 12 still verify.
const BCRYPT_COST = 10;

// Cost-10 hash of a discarded random string. Comparing against it makes unknown-email
// and no-password logins take the same time as real ones. Must match BCRYPT_COST.
const DUMMY_HASH = '$2b$10$zav6F6Pvrsbp8W4fwb8vdO7cqxj1Fmk/OHNATLySun43/KhVMzk2C';

export function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, BCRYPT_COST);
}

export function verifyPassword(password: string, hash: string): Promise<boolean> {
  return bcrypt.compare(password, hash);
}

// Always performs exactly one bcrypt compare, whether or not a hash exists.
export async function verifyPasswordOrDummy(password: string, hash: string | null | undefined): Promise<boolean> {
  if (hash) return verifyPassword(password, hash);
  await verifyPassword(password, DUMMY_HASH);
  return false;
}
