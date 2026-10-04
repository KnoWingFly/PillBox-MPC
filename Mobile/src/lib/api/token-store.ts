import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

// Tokens live only in expo-secure-store (Keychain / Keystore). Web has no secure store,
// so there they are kept in memory for the tab's lifetime and never persisted.
const KEYS = {
  access: 'pillcare.access_token',
  refresh: 'pillcare.refresh_token',
  pushTokenId: 'pillcare.push_token_id',
} as const;
type Key = keyof typeof KEYS;

const memory = new Map<string, string>();
const useMemory = Platform.OS === 'web';

async function get(key: Key): Promise<string | null> {
  if (useMemory) return memory.get(KEYS[key]) ?? null;
  return SecureStore.getItemAsync(KEYS[key]);
}

async function set(key: Key, value: string): Promise<void> {
  if (useMemory) return void memory.set(KEYS[key], value);
  return SecureStore.setItemAsync(KEYS[key], value);
}

async function remove(key: Key): Promise<void> {
  if (useMemory) return void memory.delete(KEYS[key]);
  return SecureStore.deleteItemAsync(KEYS[key]);
}

export const tokenStore = {
  getAccessToken: () => get('access'),
  getRefreshToken: () => get('refresh'),
  async setTokens(accessToken: string, refreshToken: string) {
    await Promise.all([set('access', accessToken), set('refresh', refreshToken)]);
  },
  async clear() {
    await Promise.all([remove('access'), remove('refresh'), remove('pushTokenId')]);
  },
  getPushTokenId: () => get('pushTokenId'),
  setPushTokenId: (id: string) => set('pushTokenId', id),
};
