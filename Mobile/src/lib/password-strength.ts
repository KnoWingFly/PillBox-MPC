// Password rules for the sign-up form. The auth server only enforces the length
// (src/server/schemas.ts); the digit rule and the strength meter are client-side guidance.
import { AppConfig } from '@/config';
import { Strings } from '@/constants/strings';

/** Number of bars in the strength meter; also the highest score. */
export const PASSWORD_STRENGTH_STEPS = 4;
/** Length that earns the extra "long password" point. */
const LONG_PASSWORD_LENGTH = 12;

const HAS_DIGIT = /\d/;
const HAS_MIXED_CASE = /(?=.*[a-z])(?=.*[A-Z])/;
const HAS_SYMBOL = /[^A-Za-z0-9]/;

/** 0 = empty, 1..PASSWORD_STRENGTH_STEPS = weak..very strong. */
export function passwordStrength(password: string): number {
  if (!password) return 0;
  const checks = [
    password.length >= AppConfig.passwordMinLength && HAS_DIGIT.test(password),
    HAS_MIXED_CASE.test(password),
    HAS_SYMBOL.test(password),
    password.length >= LONG_PASSWORD_LENGTH,
  ];
  return Math.max(1, checks.filter(Boolean).length);
}

/** bcrypt only reads the first 72 BYTES; emoji and accented letters take several bytes each. */
function utf8Length(value: string): number {
  return new TextEncoder().encode(value).length;
}

/** Validation message for a new password, or null when it is acceptable. */
export function newPasswordProblem(password: string): string | null {
  const v = Strings.validation;
  if (password.length < AppConfig.passwordMinLength) return v.passwordTooShort(AppConfig.passwordMinLength);
  if (utf8Length(password) > AppConfig.passwordMaxLength) return v.passwordTooLong(AppConfig.passwordMaxLength);
  if (!HAS_DIGIT.test(password)) return v.passwordNeedsDigit;
  return null;
}
