// Auth/settings API smoke test.
// Usage (dev server running, RESEND_API_KEY unset so OTPs go to .dev-last-otp.json):
//   API_URL=http://localhost:8081 pnpm exec tsx scripts/auth-smoke.ts
// Run from the project root (the dev server writes .dev-last-otp.json to its cwd).
import { readFile } from 'node:fs/promises';

const API_URL = (process.env.API_URL ?? 'http://localhost:8081').replace(/\/+$/, '');
const stamp = Date.now();
const EMAIL = `smoke+${stamp}@example.test`;
const PASSWORD_1 = 'SmokePass-1!';
const PASSWORD_2 = 'SmokePass-2!';
const PASSWORD_3 = 'SmokePass-3!';

type Res = { status: number; body: any };
type Tokens = { access_token: string; refresh_token: string; token_type: string; expires_in: number };

let passed = 0;
let currentPassword = PASSWORD_1;
let accountDeleted = false;

async function call(method: string, path: string, body?: unknown, accessToken?: string): Promise<Res> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  return { status: res.status, body: text ? JSON.parse(text) : null };
}

function check(name: string, condition: boolean, res?: Res): void {
  if (!condition) {
    throw new Error(`FAIL: ${name}${res ? ` (status ${res.status}, body ${JSON.stringify(res.body)})` : ''}`);
  }
  passed++;
  console.log(`  ok  ${name}`);
}

function expectError(name: string, res: Res, status: number, code: string): void {
  check(name, res.status === status && res.body?.error?.code === code, res);
}

function isTokenResponse(body: any): boolean {
  return (
    typeof body?.access_token === 'string' &&
    typeof body?.refresh_token === 'string' &&
    body?.token_type === 'Bearer' &&
    body?.expires_in === 900
  );
}

async function login(password = currentPassword): Promise<Tokens> {
  const res = await call('POST', '/api/auth/login', { email: EMAIL, password });
  if (res.status !== 200) throw new Error(`login failed: ${res.status} ${JSON.stringify(res.body)}`);
  return res.body;
}

async function readDevOtp(email: string): Promise<string> {
  const file = JSON.parse(await readFile('.dev-last-otp.json', 'utf8')) as Record<string, string>;
  const code = file[email];
  if (!code) throw new Error('OTP not found in .dev-last-otp.json (is RESEND_API_KEY unset on the server?)');
  return code;
}

async function main(): Promise<void> {
  console.log(`API_URL=${API_URL}\nemail=${EMAIL}\n`);

  console.log('register');
  const reg = await call('POST', '/api/auth/register', {
    full_name: 'Smoke Test',
    email: `  ${EMAIL.toUpperCase()} `, // trimmed + lowercased by the server
    phone_number: '+6281234567890',
    password: PASSWORD_1,
    timezone: 'Asia/Jakarta',
  });
  check('register -> 201 with tokens', reg.status === 201 && isTokenResponse(reg.body), reg);
  check('register returns caregiver.created_at', typeof reg.body.caregiver?.created_at === 'string', reg);

  const dup = await call('POST', '/api/auth/register', {
    full_name: 'Smoke Dup',
    email: EMAIL,
    phone_number: '+6281234567890',
    password: PASSWORD_1,
    timezone: 'Asia/Jakarta',
  });
  expectError('duplicate email -> 409', dup, 409, 'EMAIL_ALREADY_REGISTERED');

  const invalid = await call('POST', '/api/auth/register', {
    full_name: '',
    email: 'not-an-email',
    phone_number: '0812',
    password: 'short',
    timezone: 'Mars/Olympus',
  });
  expectError('invalid body -> 422', invalid, 422, 'VALIDATION_ERROR');

  console.log('login');
  const ok = await call('POST', '/api/auth/login', { email: EMAIL, password: PASSWORD_1 });
  check('login -> 200', ok.status === 200 && isTokenResponse(ok.body) && ok.body.caregiver?.full_name === 'Smoke Test', ok);
  expectError('wrong password -> 401', await call('POST', '/api/auth/login', { email: EMAIL, password: 'nope-nope' }), 401, 'INVALID_CREDENTIALS');
  expectError(
    'unknown email -> 401 (same error)',
    await call('POST', '/api/auth/login', { email: `nobody+${stamp}@example.test`, password: PASSWORD_1 }),
    401,
    'INVALID_CREDENTIALS',
  );
  let session: Tokens = ok.body;

  console.log('setting');
  expectError('GET setting without token -> 401', await call('GET', '/api/setting'), 401, 'UNAUTHORIZED');
  expectError('GET setting with garbage token -> 401', await call('GET', '/api/setting', undefined, 'garbage'), 401, 'UNAUTHORIZED');
  const get = await call('GET', '/api/setting', undefined, session.access_token);
  check(
    'GET setting -> 200 with defaults',
    get.status === 200 &&
      get.body.email === EMAIL &&
      get.body.has_password === true &&
      get.body.google_linked === false &&
      get.body.interface_language === 'ID' &&
      get.body.display_mode === 'LIGHT',
    get,
  );
  const put = await call('PUT', '/api/setting', { full_name: 'Smoke Renamed', display_mode: 'DARK' }, session.access_token);
  check('PUT setting -> 200 updated', put.status === 200 && put.body.full_name === 'Smoke Renamed' && put.body.display_mode === 'DARK', put);
  expectError('PUT setting empty body -> 422', await call('PUT', '/api/setting', {}, session.access_token), 422, 'VALIDATION_ERROR');
  expectError('PUT setting email -> 422', await call('PUT', '/api/setting', { email: 'x@example.test' }, session.access_token), 422, 'VALIDATION_ERROR');

  console.log('push tokens');
  const pushBody = { token: `ExponentPushToken[smoke-${stamp}]`, platform: 'ANDROID', device_label: 'Smoke device' };
  const push1 = await call('POST', '/api/setting/push-tokens', pushBody, session.access_token);
  const push2 = await call('POST', '/api/setting/push-tokens', pushBody, session.access_token);
  check('push POST -> 200', push1.status === 200 && typeof push1.body.id === 'string', push1);
  check('push POST twice is idempotent (same id)', push2.status === 200 && push2.body.id === push1.body.id, push2);
  const list = await call('GET', '/api/setting/push-tokens', undefined, session.access_token);
  check('push list has exactly 1', list.status === 200 && Array.isArray(list.body) && list.body.length === 1, list);
  const del = await call('DELETE', `/api/setting/push-tokens/${push1.body.id}`, undefined, session.access_token);
  check('push DELETE -> 204', del.status === 204, del);
  expectError('push DELETE again -> 404', await call('DELETE', `/api/setting/push-tokens/${push1.body.id}`, undefined, session.access_token), 404, 'NOT_FOUND');

  console.log('refresh rotation + reuse detection');
  const oldRefresh = session.refresh_token;
  const rotated = await call('POST', '/api/auth/refresh', { refresh_token: oldRefresh });
  check('refresh -> 200 new pair', rotated.status === 200 && isTokenResponse(rotated.body) && rotated.body.refresh_token !== oldRefresh, rotated);
  expectError('reuse OLD refresh token -> 401', await call('POST', '/api/auth/refresh', { refresh_token: oldRefresh }), 401, 'REFRESH_TOKEN_INVALID');
  expectError(
    'family revoked: NEW refresh token also -> 401',
    await call('POST', '/api/auth/refresh', { refresh_token: rotated.body.refresh_token }),
    401,
    'REFRESH_TOKEN_INVALID',
  );

  console.log('forgot / reset password');
  const unknownForgot = await call('POST', '/api/auth/forgot-password', { email: `nobody+${stamp}@example.test` });
  check('forgot unknown email -> 200 OTP_SENT_TO_EMAIL', unknownForgot.status === 200 && unknownForgot.body.message === 'OTP_SENT_TO_EMAIL', unknownForgot);
  session = await login();
  const forgot = await call('POST', '/api/auth/forgot-password', { email: EMAIL });
  check('forgot -> 200', forgot.status === 200 && forgot.body.message === 'OTP_SENT_TO_EMAIL', forgot);
  const otp = await readDevOtp(EMAIL);
  check('OTP captured by dev email driver', /^\d{6}$/.test(otp));
  const wrongOtp = otp === '000000' ? '111111' : '000000';
  expectError(
    'reset with wrong OTP -> 400',
    await call('POST', '/api/auth/reset-password', { email: EMAIL, otp_code: wrongOtp, new_password: PASSWORD_2 }),
    400,
    'INVALID_OTP',
  );
  expectError(
    'reset for unknown email -> 400 (same error)',
    await call('POST', '/api/auth/reset-password', { email: `nobody+${stamp}@example.test`, otp_code: otp, new_password: PASSWORD_2 }),
    400,
    'INVALID_OTP',
  );
  const reset = await call('POST', '/api/auth/reset-password', { email: EMAIL, otp_code: otp, new_password: PASSWORD_2 });
  check('reset -> 200', reset.status === 200 && reset.body.message === 'PASSWORD_RESET_SUCCESS', reset);
  currentPassword = PASSWORD_2;
  expectError(
    'OTP cannot be reused',
    await call('POST', '/api/auth/reset-password', { email: EMAIL, otp_code: otp, new_password: PASSWORD_3 }),
    400,
    'INVALID_OTP',
  );
  expectError('reset revoked existing refresh tokens', await call('POST', '/api/auth/refresh', { refresh_token: session.refresh_token }), 401, 'REFRESH_TOKEN_INVALID');
  expectError('old password no longer works', await call('POST', '/api/auth/login', { email: EMAIL, password: PASSWORD_1 }), 401, 'INVALID_CREDENTIALS');

  console.log('change password');
  const other = await login(); // a second session that must be revoked
  session = await login();
  expectError(
    'change with wrong old password -> 401',
    await call('PUT', '/api/auth/change-password', { old_password: 'wrong-wrong', new_password: PASSWORD_3 }, session.access_token),
    401,
    'INVALID_OLD_PASSWORD',
  );
  const change = await call('PUT', '/api/auth/change-password', { old_password: PASSWORD_2, new_password: PASSWORD_3 }, session.access_token);
  check('change-password -> 200', change.status === 200 && change.body.message === 'PASSWORD_CHANGED_SUCCESS', change);
  currentPassword = PASSWORD_3;
  expectError('other session revoked', await call('POST', '/api/auth/refresh', { refresh_token: other.refresh_token }), 401, 'REFRESH_TOKEN_INVALID');
  const kept = await call('POST', '/api/auth/refresh', { refresh_token: session.refresh_token });
  check('current session kept', kept.status === 200 && isTokenResponse(kept.body), kept);
  session = kept.body;

  console.log('logout');
  const out1 = await call('POST', '/api/auth/logout', { refresh_token: session.refresh_token });
  const out2 = await call('POST', '/api/auth/logout', { refresh_token: session.refresh_token });
  const out3 = await call('POST', '/api/auth/logout', { refresh_token: 'unknown-token' });
  check('logout -> 204, idempotent', out1.status === 204 && out2.status === 204 && out3.status === 204);
  expectError('refresh after logout -> 401', await call('POST', '/api/auth/refresh', { refresh_token: session.refresh_token }), 401, 'REFRESH_TOKEN_INVALID');

  console.log('google');
  expectError(
    'google with invalid token -> 401',
    await call('POST', '/api/auth/google', { supabase_access_token: 'not-a-real-token', timezone: 'Asia/Jakarta' }),
    401,
    'GOOGLE_TOKEN_INVALID',
  );

  console.log('delete account');
  session = await login();
  expectError('delete with wrong password -> 401', await call('DELETE', '/api/setting', { password: 'wrong-wrong' }, session.access_token), 401, 'INVALID_PASSWORD');
  const gone = await call('DELETE', '/api/setting', { password: currentPassword }, session.access_token);
  check('delete account -> 204', gone.status === 204, gone);
  accountDeleted = true;
  expectError('login after delete -> 401', await call('POST', '/api/auth/login', { email: EMAIL, password: currentPassword }), 401, 'INVALID_CREDENTIALS');
  expectError('old access token after delete -> 401', await call('GET', '/api/setting', undefined, session.access_token), 401, 'UNAUTHORIZED');
}

async function cleanup(): Promise<void> {
  if (accountDeleted) return;
  try {
    const { access_token } = await login();
    const res = await call('DELETE', '/api/setting', { password: currentPassword }, access_token);
    console.log(`cleanup: delete account -> ${res.status}`);
  } catch (err) {
    console.log(`cleanup: could not delete ${EMAIL}: ${(err as Error).message}`);
  }
}

main()
  .then(() => console.log(`\nPASS (${passed} checks)`))
  .catch(async (err) => {
    console.error(`\n${(err as Error).message}\n(${passed} checks passed before failure)`);
    process.exitCode = 1;
  })
  .finally(cleanup);
