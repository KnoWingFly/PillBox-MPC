import { apiFetch } from './client';

export type InterfaceLanguage = 'ID' | 'EN';
export type DisplayMode = 'LIGHT' | 'DARK';
export type PushPlatform = 'ANDROID' | 'IOS';

export type Setting = {
  id: string;
  full_name: string;
  email: string;
  phone_number: string | null;
  timezone: string;
  google_linked: boolean;
  has_password: boolean;
  interface_language: InterfaceLanguage;
  display_mode: DisplayMode;
  created_at: string;
};

export type UpdateSettingInput = Partial<{
  full_name: string;
  phone_number: string | null;
  timezone: string;
  interface_language: InterfaceLanguage;
  display_mode: DisplayMode;
}>;

export type DeleteAccountInput = { password: string } | { confirm: 'DELETE' };

export type PushTokenItem = { id: string; platform: PushPlatform; device_label: string | null; created_at: string };

export const settingApi = {
  get: () => apiFetch<Setting>('/api/setting'),
  update: (body: UpdateSettingInput) => apiFetch<Setting>('/api/setting', { method: 'PUT', body }),
  deleteAccount: (body: DeleteAccountInput) => apiFetch<void>('/api/setting', { method: 'DELETE', body }),
  listPushTokens: () => apiFetch<PushTokenItem[]>('/api/setting/push-tokens'),
  registerPushToken: (body: { token: string; platform: PushPlatform; device_label?: string | null }) =>
    apiFetch<{ id: string; platform: PushPlatform; created_at: string }>('/api/setting/push-tokens', {
      method: 'POST',
      body,
    }),
  deletePushToken: (id: string) =>
    apiFetch<void>(`/api/setting/push-tokens/${encodeURIComponent(id)}`, { method: 'DELETE' }),
};
