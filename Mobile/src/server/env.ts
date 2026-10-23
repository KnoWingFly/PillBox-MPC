// Server-only environment access. Values are read lazily so a missing variable
// only fails the endpoint that needs it, with a clear message in the server log.

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required server env var: ${name}`);
  return value;
}

export const env = {
  get jwtAccessSecret(): string {
    const value = required('JWT_ACCESS_SECRET');
    if (value.length < 32) throw new Error('JWT_ACCESS_SECRET must be at least 32 characters');
    return value;
  },
  /** Optional: separate pepper for OTP hashes. Unset -> derived from JWT_ACCESS_SECRET (see otp.ts). */
  get otpPepper(): string | undefined {
    return process.env.OTP_PEPPER || undefined;
  },
  // The project URL is public, so the server reuses the client variable instead of a second copy.
  get supabaseUrl(): string {
    return required('EXPO_PUBLIC_SUPABASE_URL');
  },
  /** New-style secret key (sb_secret_...). Needed only for Google sign-in and deleting Google-linked accounts. */
  get supabaseSecretKey(): string {
    return required('SUPABASE_SECRET_KEY');
  },
  get resendApiKey(): string | undefined {
    return process.env.RESEND_API_KEY || undefined;
  },
  /** Only needed when RESEND_API_KEY is set. */
  get emailFrom(): string {
    return required('EMAIL_FROM');
  },
  get isProduction(): boolean {
    return process.env.NODE_ENV === 'production';
  },
};
