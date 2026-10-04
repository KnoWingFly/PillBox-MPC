import { createContext, useCallback, useContext, useEffect, useMemo, useState, type PropsWithChildren } from 'react';

import { authApi, deviceTimezone, type RegisterInput } from '@/lib/api/auth';
import { ApiError, onSessionExpired, type TokenResponse } from '@/lib/api/client';
import { settingApi } from '@/lib/api/setting';
import { tokenStore } from '@/lib/api/token-store';
import { getGoogleIdToken, googleSignOut } from '@/lib/google-signin';
import { registerPushToken, unregisterPushToken } from '@/lib/push-token';
import { getSupabase } from '@root/utils/supabase';

export type AuthStatus = 'loading' | 'signedOut' | 'signedIn';
export type AuthUser = { id: string; full_name: string; email?: string };

type AuthContextValue = {
  status: AuthStatus;
  user: AuthUser | null;
  /** Kept for existing callers. */
  isLoading: boolean;
  isLoggedIn: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (input: Omit<RegisterInput, 'timezone'>) => Promise<void>;
  /** Resolves false when the user cancels the Google picker. */
  signInWithGoogle: () => Promise<boolean>;
  signOut: () => Promise<void>;
  forgotPassword: (email: string) => Promise<void>;
  resetPassword: (email: string, otpCode: string, newPassword: string) => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuthContext(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuthContext must be used inside <AuthProvider>');
  return ctx;
}

export default function AuthProvider({ children }: PropsWithChildren) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<AuthUser | null>(null);

  const markSignedOut = useCallback(() => {
    setUser(null);
    setStatus('signedOut');
  }, []);

  // Restore on launch: a stored refresh token means "signed in"; the profile call also
  // exercises the refresh path. Offline keeps the session instead of signing out.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (!(await tokenStore.getRefreshToken())) return markSignedOut();
        const setting = await settingApi.get();
        if (cancelled) return;
        setUser({ id: setting.id, full_name: setting.full_name, email: setting.email });
        setStatus('signedIn');
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.code === 'NETWORK_ERROR') setStatus('signedIn');
        else {
          await tokenStore.clear();
          markSignedOut();
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [markSignedOut]);

  useEffect(() => onSessionExpired(markSignedOut), [markSignedOut]);

  const startSession = useCallback(async (tokens: TokenResponse, nextUser: AuthUser) => {
    await tokenStore.setTokens(tokens.access_token, tokens.refresh_token);
    setUser(nextUser);
    setStatus('signedIn');
    void registerPushToken();
  }, []);

  const signIn = useCallback<AuthContextValue['signIn']>(
    async (email, password) => {
      const res = await authApi.login({ email, password });
      await startSession(res, { id: res.caregiver.id, full_name: res.caregiver.full_name, email });
    },
    [startSession],
  );

  const signUp = useCallback<AuthContextValue['signUp']>(
    async (input) => {
      const res = await authApi.register({ ...input, timezone: deviceTimezone() });
      await startSession(res, { id: res.caregiver.id, full_name: res.caregiver.full_name, email: input.email });
    },
    [startSession],
  );

  const signInWithGoogle = useCallback<AuthContextValue['signInWithGoogle']>(async () => {
    const idToken = await getGoogleIdToken();
    if (!idToken) return false; // cancelled: silent

    const supabase = getSupabase();
    try {
      const { data, error } = await supabase.auth.signInWithIdToken({ provider: 'google', token: idToken });
      if (error || !data.session) throw new ApiError(401, 'GOOGLE_TOKEN_INVALID', error?.message ?? 'No session');
      const res = await authApi.google({
        supabase_access_token: data.session.access_token,
        timezone: deviceTimezone(),
      });
      await startSession(res, res.caregiver);
      return true;
    } finally {
      // Never keep a second live session: ours is the only one.
      await supabase.auth.signOut({ scope: 'local' }).catch(() => undefined);
    }
  }, [startSession]);

  const signOut = useCallback(async () => {
    await unregisterPushToken(); // needs the access token, so before clearing
    const refreshToken = await tokenStore.getRefreshToken();
    if (refreshToken) await authApi.logout(refreshToken).catch(() => undefined);
    await tokenStore.clear();
    await googleSignOut();
    markSignedOut();
  }, [markSignedOut]);

  const forgotPassword = useCallback(async (email: string) => {
    await authApi.forgotPassword(email);
  }, []);

  const resetPassword = useCallback(async (email: string, otpCode: string, newPassword: string) => {
    await authApi.resetPassword({ email, otp_code: otpCode, new_password: newPassword });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      isLoading: status === 'loading',
      isLoggedIn: status === 'signedIn',
      signIn,
      signUp,
      signInWithGoogle,
      signOut,
      forgotPassword,
      resetPassword,
    }),
    [status, user, signIn, signUp, signInWithGoogle, signOut, forgotPassword, resetPassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
