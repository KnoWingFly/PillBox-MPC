import { hmacSha256Hex, timingSafeEqual } from './crypto';
import { env } from './env';

export const OTP_TTL_MS = 10 * 60 * 1000;
export const OTP_RESEND_COOLDOWN_MS = 60 * 1000;
export const OTP_MAX_ATTEMPTS = 5;

// Uniform 6-digit code: rejection sampling avoids modulo bias.
export function generateOtpCode(): string {
  const limit = Math.floor(0x100000000 / 1_000_000) * 1_000_000;
  const buf = new Uint32Array(1);
  do crypto.getRandomValues(buf);
  while (buf[0] >= limit);
  return String(buf[0] % 1_000_000).padStart(6, '0');
}

// Use OTP_PEPPER when set; otherwise derive a separate key from JWT_ACCESS_SECRET so the
// two uses never share the same key.
async function otpKey(): Promise<string> {
  return env.otpPepper ?? hmacSha256Hex(env.jwtAccessSecret, 'pillcare:otp-pepper:v1');
}

export async function hashOtp(code: string): Promise<string> {
  return hmacSha256Hex(await otpKey(), code);
}

export async function otpMatches(code: string, codeHash: string): Promise<boolean> {
  return timingSafeEqual(await hashOtp(code), codeHash);
}
