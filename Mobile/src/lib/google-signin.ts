import { Platform } from 'react-native';

import { Strings } from '@/constants/strings';

type GoogleSigninModule = typeof import('@react-native-google-signin/google-signin');

let cached: GoogleSigninModule | null | undefined;
let nativeUnavailableMessage: string = Strings.auth.googleNativeModuleUnavailable;

// The native module is absent in Expo Go (and on web). Requiring it there throws, so it is
// loaded lazily and guarded; callers check isGoogleSignInAvailable() first.
function load(): GoogleSigninModule | null {
  if (cached !== undefined) return cached;
  cached = null;

  const webClientId = process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID?.trim();
  if (Platform.OS === 'web') return cached;
  if (!webClientId) {
    nativeUnavailableMessage = Strings.auth.googleWebClientMissing;
    return cached;
  }

  // Avoid Constants.expoGoConfig/appOwnership as a gate: SDK 58 can expose an embedded
  // manifest through expoGoConfig outside Expo Go. Resolving the native module is authoritative.
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod: GoogleSigninModule = require('@react-native-google-signin/google-signin');
    mod.GoogleSignin.configure({
      webClientId,
      iosClientId: process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID?.trim() || undefined,
    });
    cached = mod;
  } catch {
    nativeUnavailableMessage = Strings.auth.googleNativeModuleUnavailable;
    cached = null;
  }
  return cached;
}

export function isGoogleSignInAvailable(): boolean {
  return getGoogleSignInUnavailableMessage() === null;
}

/** Returns a safe, user-facing reason when Google Sign-In cannot start. Never includes client IDs. */
export function getGoogleSignInUnavailableMessage(): string | null {
  if (Platform.OS === 'web') {
    return process.env.EXPO_PUBLIC_SUPABASE_URL && process.env.EXPO_PUBLIC_SUPABASE_KEY
      ? null
      : Strings.auth.googleWebConfigMissing;
  }
  return load() ? null : nativeUnavailableMessage;
}

/** Returns a Google ID token, or null when the user cancels. */
export async function getGoogleIdToken(): Promise<string | null> {
  const mod = load();
  if (!mod) {
    throw Object.assign(new Error('Google Sign-In is not available in this build'), {
      code: 'GOOGLE_SIGN_IN_UNAVAILABLE',
      userMessage: nativeUnavailableMessage,
    });
  }
  const { GoogleSignin, isSuccessResponse, isErrorWithCode, statusCodes } = mod;

  try {
    if (Platform.OS === 'android') await GoogleSignin.hasPlayServices({ showPlayServicesUpdateDialog: true });
    const response = await GoogleSignin.signIn();
    if (!isSuccessResponse(response)) return null; // cancelled
    if (!response.data.idToken) throw new Error('Google did not return an ID token (check webClientId)');
    return response.data.idToken;
  } catch (err) {
    if (isErrorWithCode(err) && (err.code === statusCodes.SIGN_IN_CANCELLED || err.code === statusCodes.IN_PROGRESS)) {
      return null;
    }
    throw err;
  }
}

/** Clears the cached Google account so the picker shows next time. Best effort. */
export async function googleSignOut(): Promise<void> {
  try {
    await load()?.GoogleSignin.signOut();
  } catch {
    // ignore
  }
}
