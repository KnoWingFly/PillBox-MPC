import { z } from 'zod';

const email = z.string().trim().toLowerCase().pipe(z.email().max(254));
const password = z.string().min(8, 'Password must be at least 8 characters').max(72, 'Password is too long');
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
  password: z.string().min(1).max(72),
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
  old_password: z.string().min(1).max(72).optional(),
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
  password: z.string().min(1).max(72).optional(),
  confirm: z.literal('DELETE').optional(),
});

export const pushTokenSchema = z.object({
  token: z.string().trim().min(1).max(255),
  platform: z.enum(['ANDROID', 'IOS']),
  device_label: z.string().trim().max(100).nullish(),
});
