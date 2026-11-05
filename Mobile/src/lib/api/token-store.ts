import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

// Where the session lives, by platform and "Ingat saya":
//   native, remembered  -> expo-secure-store (Keychain / Keystore)
//   native, not         -> memory: a cold start finds no session, the only reliable
//                          "clear on app close" (React Native has no kill hook)
//   web, remembered     -> localStorage (survives reloads and browser restarts)
//   web, not            -> sessionStorage (survives reloads, ends when the tab closes)
// Web storage is readable by any script on the page; see the XSS note in the handoff list
// (an httpOnly refresh cookie needs the auth server, which is out of scope here).
const KEYS = {
  access: 'pillcare.access_token',
  refresh: 'pillcare.refresh_token',
  pushTokenId: 'pillcare.push_token_id',
  /** Epoch ms of the interactive login; caps a remembered session at SESSION_MAX_AGE_MS. */
  loginAt: 'pillcare.login_at',
} as const;
type Key = keyof typeof KEYS;

/** A remembered session ends this long after the user last typed credentials. */
export const SESSION_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;

// Values above ~2 KB have been rejected by some iOS Keychain versions. Our tokens are far
// smaller, but a value that grows is split into chunks instead of failing the login.
const CHUNK_SIZE = 2000;
const CHUNK_MARKER = '__chunks:';

const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
};

type Backend = 'secure' | 'memory' | 'local' | 'session';

const memory = new Map<string, string>();
const isWeb = Platform.OS === 'web';

/** null on web until first use: decided by which storage holds a session (see webBackend). */
let backend: Backend | null = isWeb ? null : 'secure';

// Storage access throws in some private-browsing modes and when site data is blocked.
function webStorage(kind: 'local' | 'session'): Storage | null {
  try {
    return kind === 'local' ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

function webBackend(): Backend {
  if (webStorage('local')?.getItem(KEYS.refresh)) return 'local';
  if (webStorage('session')?.getItem(KEYS.refresh)) return 'session';
  return 'session';
}

function current(): Backend {
  backend ??= webBackend();
  return backend;
}

async function secureGet(name: string): Promise<string | null> {
  const value = await SecureStore.getItemAsync(name, OPTIONS);
  if (!value?.startsWith(CHUNK_MARKER)) return value;
  const count = Number(value.slice(CHUNK_MARKER.length));
  const parts = await Promise.all(Array.from({ length: count }, (_, i) => SecureStore.getItemAsync(`${name}.${i}`, OPTIONS)));
  return parts.some((p) => p === null) ? null : parts.join('');
}

async function secureRemove(name: string): Promise<void> {
  const value = await SecureStore.getItemAsync(name, OPTIONS).catch(() => null);
  if (value?.startsWith(CHUNK_MARKER)) {
    const count = Number(value.slice(CHUNK_MARKER.length));
    await Promise.all(Array.from({ length: count }, (_, i) => SecureStore.deleteItemAsync(`${name}.${i}`, OPTIONS)));
  }
  await SecureStore.deleteItemAsync(name, OPTIONS);
}

function chunkCount(value: string | null): number {
  return value?.startsWith(CHUNK_MARKER) ? Number(value.slice(CHUNK_MARKER.length)) : 0;
}

// Never deletes before writing: a crash between a delete and the write would lose the session.
// The new value is written first, then chunks the old value used and the new one does not are removed.
async function secureSet(name: string, value: string): Promise<void> {
  const oldChunks = chunkCount(await SecureStore.getItemAsync(name, OPTIONS).catch(() => null));
  let newChunks = 0;
  if (value.length <= CHUNK_SIZE) {
    await SecureStore.setItemAsync(name, value, OPTIONS);
  } else {
    const chunks = value.match(new RegExp(`[\\s\\S]{1,${CHUNK_SIZE}}`, 'g')) ?? [];
    for (const [i, chunk] of chunks.entries()) await SecureStore.setItemAsync(`${name}.${i}`, chunk, OPTIONS);
    await SecureStore.setItemAsync(name, `${CHUNK_MARKER}${chunks.length}`, OPTIONS);
    newChunks = chunks.length;
  }
  for (let i = newChunks; i < oldChunks; i += 1) await SecureStore.deleteItemAsync(`${name}.${i}`, OPTIONS).catch(() => undefined);
}

async function get(key: Key): Promise<string | null> {
  const where = current();
  if (where === 'secure') return secureGet(KEYS[key]);
  if (where === 'memory') return memory.get(KEYS[key]) ?? null;
  const storage = webStorage(where);
  // Storage unavailable: fall back to memory so the tab still works until it is reloaded.
  return storage ? storage.getItem(KEYS[key]) : (memory.get(KEYS[key]) ?? null);
}

async function set(key: Key, value: string): Promise<void> {
  const where = current();
  if (where === 'secure') return secureSet(KEYS[key], value);
  const storage = where === 'memory' ? null : webStorage(where);
  try {
    if (storage) return storage.setItem(KEYS[key], value);
  } catch {
    // quota exceeded or storage blocked: keep it in memory below
  }
  memory.set(KEYS[key], value);
}

/** Removes `key` from every store except `keep` (the one a new session is about to write to). */
async function removeEverywhere(key: Key, keep: Backend | null = null): Promise<void> {
  if (keep !== 'memory') memory.delete(KEYS[key]);
  if (isWeb) {
    if (keep !== 'local') webStorage('local')?.removeItem(KEYS[key]);
    if (keep !== 'session') webStorage('session')?.removeItem(KEYS[key]);
  } else if (keep !== 'secure') {
    await secureRemove(KEYS[key]);
  }
}

/** Writes one at a time, in order: the refresh token first, so a failure part-way never leaves an
 * access token without the refresh token that renews it. */
async function setInOrder(entries: [Key, string][]): Promise<void> {
  for (const [key, value] of entries) await set(key, value);
}

export const tokenStore = {
  getAccessToken: () => get('access'),
  getRefreshToken: () => get('refresh'),
  /**
   * Starts a session. `remember` false: native keeps the tokens in memory (lost when the app is
   * killed), web keeps them in sessionStorage (lost when the tab closes).
   * Every other store is cleared so a previous remembered session cannot linger beside a new one;
   * the target store is overwritten in place, never emptied first.
   */
  async startSession(accessToken: string, refreshToken: string, remember: boolean) {
    const target: Backend = isWeb ? (remember ? 'local' : 'session') : remember ? 'secure' : 'memory';
    await Promise.all((Object.keys(KEYS) as Key[]).map((key) => removeEverywhere(key, target)));
    backend = target;
    await removeEverywhere('pushTokenId'); // belongs to the previous account
    await setInOrder([
      ['refresh', refreshToken],
      ['access', accessToken],
      ['loginAt', String(Date.now())],
    ]);
  },
  /** Stores a rotated token pair in whichever store the current session uses. */
  async setTokens(accessToken: string, refreshToken: string) {
    await setInOrder([
      ['refresh', refreshToken],
      ['access', accessToken],
    ]);
  },
  async getLoginAt(): Promise<number | null> {
    const raw = await get('loginAt');
    const value = raw === null ? NaN : Number(raw);
    return Number.isFinite(value) ? value : null;
  },
  markLoginNow: () => set('loginAt', String(Date.now())),
  async clear() {
    await Promise.all((Object.keys(KEYS) as Key[]).map((key) => removeEverywhere(key)));
    backend = isWeb ? null : 'secure';
  },
  getPushTokenId: () => get('pushTokenId'),
  setPushTokenId: (id: string) => set('pushTokenId', id),
};
