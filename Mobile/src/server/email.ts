import { env } from './env';

type Email = { to: string; subject: string; text: string };

const DEV_OTP_FILE = '.dev-last-otp.json';

async function sendWithResend(apiKey: string, email: Email): Promise<void> {
  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ from: env.emailFrom, to: [email.to], subject: email.subject, text: email.text }),
  });
  if (!res.ok) {
    // Resend's error body ({ name, message }) explains the cause, e.g. test-mode recipient limits.
    let reason = '';
    try {
      const body = (await res.json()) as { name?: string; message?: string };
      reason = [body.name, body.message].filter(Boolean).join(': ');
    } catch {
      // non-JSON body
    }
    throw new Error(`Resend request failed with status ${res.status}${reason ? ` (${reason})` : ''}`);
  }
}

// Dev-only driver: prints the OTP and records it for the smoke test. Never used in production.
async function sendWithConsole(email: Email, otpCode: string): Promise<void> {
  console.log(`[email:dev] to=${email.to} subject="${email.subject}" otp=${otpCode}`);
  const fs = await import('node:fs/promises');
  let existing: Record<string, string> = {};
  try {
    existing = JSON.parse(await fs.readFile(DEV_OTP_FILE, 'utf8'));
  } catch {
    // first write
  }
  await fs.writeFile(DEV_OTP_FILE, JSON.stringify({ ...existing, [email.to]: otpCode }, null, 2));
}

export async function sendPasswordResetOtp(to: string, code: string): Promise<void> {
  const email: Email = {
    to,
    subject: 'Kode reset kata sandi PillCare',
    text: [
      'Halo,',
      '',
      `Kode untuk mereset kata sandi PillCare Anda: ${code}`,
      'Kode ini berlaku selama 10 menit.',
      '',
      'Jika Anda tidak meminta reset kata sandi, abaikan email ini.',
    ].join('\n'),
  };

  const apiKey = env.resendApiKey;
  if (!apiKey) {
    if (env.isProduction) throw new Error('RESEND_API_KEY is required in production');
    return sendWithConsole(email, code);
  }

  try {
    await sendWithResend(apiKey, email);
  } catch (err) {
    if (env.isProduction) throw err;
    // Dev: keep the flow testable even when Resend rejects the recipient (test mode only
    // delivers to the Resend account owner's address without a verified domain).
    console.warn(`[email:dev] ${err instanceof Error ? err.message : err} -> falling back to console`);
    await sendWithConsole(email, code);
  }
}
