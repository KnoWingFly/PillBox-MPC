import { z } from 'zod';

const email = z.string().trim().toLowerCase().pipe(z.email().max(254));
// bcrypt reads only the first 72 BYTES; a longer password would be silently truncated.
const BCRYPT_MAX_BYTES = 72;
const PASSWORD_MIN_LENGTH = 8;
const withinBcryptLimit = (value: string) => new TextEncoder().encode(value).length <= BCRYPT_MAX_BYTES;
const anyPassword = z.string().min(1).refine(withinBcryptLimit, `Password must be at most ${BCRYPT_MAX_BYTES} bytes`);
const password = z
  .string()
  .min(PASSWORD_MIN_LENGTH, `Password must be at least ${PASSWORD_MIN_LENGTH} characters`)
  .refine(withinBcryptLimit, `Password must be at most ${BCRYPT_MAX_BYTES} bytes`);
const fullName = z.string().trim().min(1).max(100);
const phoneNumber = z.e164();

function isValidTimeZone(tz: string): boolean {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}
const timezone = z.string().trim().min(1).refine(isValidTimeZone, 'Invalid IANA timezone');

export const registerSchema = z.object({
  full_name: fullName,
  email,
  phone_number: phoneNumber,
  password,
  timezone,
});

export const loginSchema = z.object({
  email,
  password: anyPassword,
});

export const googleSchema = z.object({
  supabase_access_token: z.string().min(1),
  timezone,
});

export const refreshSchema = z.object({ refresh_token: z.string().min(1) });

export const forgotPasswordSchema = z.object({ email });

export const resetPasswordSchema = z.object({
  email,
  otp_code: z.string().regex(/^\d{6}$/, 'OTP must be 6 digits'),
  new_password: password,
});

export const changePasswordSchema = z.object({
  old_password: anyPassword.optional(),
  new_password: password,
});

export const updateSettingSchema = z
  .object({
    full_name: fullName,
    phone_number: phoneNumber.nullable(),
    timezone,
    interface_language: z.enum(['ID', 'EN']),
    display_mode: z.enum(['LIGHT', 'DARK']),
  })
  .partial()
  .strict()
  .refine((body) => Object.keys(body).length > 0, 'At least one field is required');

export const deleteAccountSchema = z.object({
  password: anyPassword.optional(),
  confirm: z.literal('DELETE').optional(),
});

export const pushTokenSchema = z.object({
  token: z.string().trim().min(1).max(255),
  platform: z.enum(['ANDROID', 'IOS']),
  device_label: z.string().trim().max(100).nullish(),
});
