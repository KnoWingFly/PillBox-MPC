import { apiFetch, type TokenResponse } from './client';

export type Caregiver = { id: string; full_name: string; email?: string };

export type RegisterInput = {
  full_name: string;
  email: string;
  phone_number: string;
  password: string;
  timezone: string;
};

export type LoginResponse = TokenResponse & { caregiver: { id: string; full_name: string } };
export type RegisterResponse = TokenResponse & { caregiver: { id: string; full_name: string; created_at: string } };
export type GoogleResponse = TokenResponse & {
  caregiver: { id: string; full_name: string; email: string; google_linked: true };
  is_new_account: boolean;
};

export const authApi = {
  register: (body: RegisterInput) =>
    apiFetch<RegisterResponse>('/api/auth/register', { method: 'POST', body, auth: false }),
  login: (body: { email: string; password: string }) =>
    apiFetch<LoginResponse>('/api/auth/login', { method: 'POST', body, auth: false }),
  google: (body: { supabase_access_token: string; timezone: string }) =>
    apiFetch<GoogleResponse>('/api/auth/google', { method: 'POST', body, auth: false }),
  logout: (refreshToken: string) =>
    apiFetch<void>('/api/auth/logout', { method: 'POST', body: { refresh_token: refreshToken }, auth: false }),
  forgotPassword: (email: string) =>
    apiFetch<{ message: 'OTP_SENT_TO_EMAIL' }>('/api/auth/forgot-password', {
      method: 'POST',
      body: { email },
      auth: false,
    }),
  resetPassword: (body: { email: string; otp_code: string; new_password: string }) =>
    apiFetch<{ message: 'PASSWORD_RESET_SUCCESS' }>('/api/auth/reset-password', {
      method: 'POST',
      body,
      auth: false,
    }),
  changePassword: (body: { old_password?: string; new_password: string }) =>
    apiFetch<{ message: 'PASSWORD_CHANGED_SUCCESS' }>('/api/auth/change-password', { method: 'PUT', body }),
};

export function deviceTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Jakarta';
}
