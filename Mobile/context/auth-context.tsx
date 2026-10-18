import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type PropsWithChildren } from 'react';
import { AppState } from 'react-native';

import { authApi, deviceTimezone, type RegisterInput } from '@/lib/api/auth';
import { ApiError, onSessionExpired, type TokenResponse } from '@/lib/api/client';
import { settingApi } from '@/lib/api/setting';
import { SESSION_MAX_AGE_MS, tokenStore } from '@/lib/api/token-store';
import { getGoogleIdToken, googleSignOut } from '@/lib/google-signin';
import { perfLoginStep } from '@/lib/perf';
import { registerPushToken, unregisterPushToken } from '@/lib/push-token';
import { getSupabase } from '@root/utils/supabase';
import { resetPillboxSession } from '@root/lib/api';

export type AuthStatus = 'loading' | 'signedOut' | 'signedIn';
export type AuthUser = { id: string; full_name: string; email?: string };

type AuthContextValue = {
  status: AuthStatus;
  user: AuthUser | null;
  /** Kept for existing callers. */
  isLoading: boolean;
  isLoggedIn: boolean;
  /** Why the user was sent back to the login screen (shown there once), or null. */
  sessionNotice: string | null;
  clearSessionNotice: () => void;
  /** `remember` false: the session is kept in memory only and ends when the app is closed. */
  signIn: (email: string, password: string, remember: boolean) => Promise<void>;
  signUp: (input: Omit<RegisterInput, 'timezone'>) => Promise<void>;
  /** Resolves false when the user cancels the Google picker. */
  signInWithGoogle: (remember: boolean) => Promise<boolean>;
  signOut: () => Promise<void>;
  forgotPassword: (email: string) => Promise<void>;
  resetPassword: (email: string, otpCode: string, newPassword: string) => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const NOTICE_SESSION_AGED_OUT = 'Sesi Anda telah berakhir setelah 30 hari. Silakan masuk kembali.';
const NOTICE_SESSION_EXPIRED = 'Sesi Anda telah berakhir. Silakan masuk kembali.';

async function sessionAgedOut(): Promise<boolean> {
  const loginAt = await tokenStore.getLoginAt();
  return loginAt !== null && Date.now() - loginAt > SESSION_MAX_AGE_MS;
}

export function useAuthContext(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuthContext must be used inside <AuthProvider>');
  return ctx;
}

export default function AuthProvider({ children }: PropsWithChildren) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<AuthUser | null>(null);
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);
  // Read by the session-expired listener: a request still in flight after logout also gets a 401,
  // which must not show "Sesi berakhir" on the login screen.
  const statusRef = useRef<AuthStatus>('loading');
  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  const markSignedOut = useCallback(() => {
    resetPillboxSession();
    setUser(null);
    setStatus('signedOut');
  }, []);

  // Ends the session everywhere: push token first (needs the access token), then the server-side
  // refresh-token family, then local storage. Every step is best effort so offline logout works.
  const endSession = useCallback(
    async (notice: string | null) => {
      await unregisterPushToken();
      const refreshToken = await tokenStore.getRefreshToken();
      if (refreshToken) await authApi.logout(refreshToken).catch(() => undefined);
      await tokenStore.clear();
      await googleSignOut();
      setSessionNotice(notice);
      markSignedOut();
    },
    [markSignedOut],
  );

  // Restore on launch: a stored refresh token means "signed in"; the profile call also
  // exercises the refresh path. Offline keeps the session instead of signing out.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      perfLoginStep('session_restore_started');
      try {
        if (!(await tokenStore.getRefreshToken())) {
          perfLoginStep('session_restored', { result: 'no_session' });
          return markSignedOut();
        }
        // Checked before any network call, so it also applies to an offline start.
        if (await sessionAgedOut()) {
          perfLoginStep('session_restored', { result: 'aged_out' });
          if (!cancelled) await endSession(NOTICE_SESSION_AGED_OUT);
          return;
        }
        // Sessions stored before the 30-day cap existed have no login time: start counting now.
        if ((await tokenStore.getLoginAt()) === null) await tokenStore.markLoginNow();
        const setting = await settingApi.get();
        if (cancelled) return;
        setUser({ id: setting.id, full_name: setting.full_name, email: setting.email });
        setStatus('signedIn');
        perfLoginStep('session_restored', { result: 'signed_in' });
      } catch (err) {
        if (cancelled) return;
        perfLoginStep('session_restored', { result: 'error', code: err instanceof ApiError ? err.code : 'UNKNOWN' });
        if (err instanceof ApiError && err.code === 'NETWORK_ERROR') setStatus('signedIn');
        else {
          await tokenStore.clear();
          if (err instanceof ApiError && err.code === 'UNAUTHORIZED') setSessionNotice(NOTICE_SESSION_EXPIRED);
          markSignedOut();
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [markSignedOut, endSession]);

  // Refresh token rejected mid-session (revoked, expired, reused): tokens are already cleared.
  useEffect(
    () =>
      onSessionExpired(() => {
        if (statusRef.current !== 'signedIn') return; // already signed out (or still restoring)
        setSessionNotice(NOTICE_SESSION_EXPIRED);
        markSignedOut();
      }),
    [markSignedOut],
  );

  // An app left running in the background can outlive the 30-day cap: re-check on resume.
  useEffect(() => {
    if (status !== 'signedIn') return;
    const sub = AppState.addEventListener('change', (next) => {
      if (next !== 'active') return;
      void sessionAgedOut().then((aged) => {
        if (aged) return endSession(NOTICE_SESSION_AGED_OUT);
      });
    });
    return () => sub.remove();
  }, [status, endSession]);

  const startSession = useCallback(async (tokens: TokenResponse, nextUser: AuthUser, remember: boolean) => {
    await tokenStore.startSession(tokens.access_token, tokens.refresh_token, remember);
    resetPillboxSession(); // never reuse the previous account's pillbox selection
    setSessionNotice(null);
    setUser(nextUser);
    setStatus('signedIn');
    void registerPushToken();
  }, []);

  const signIn = useCallback<AuthContextValue['signIn']>(
    async (email, password, remember) => {
      perfLoginStep('password_login_sent');
      const res = await authApi.login({ email, password });
      perfLoginStep('password_login_returned');
      await startSession(res, { id: res.caregiver.id, full_name: res.caregiver.full_name, email }, remember);
    },
    [startSession],
  );

  // A new account is remembered: sign-up has no "Ingat saya" choice.
  const signUp = useCallback<AuthContextValue['signUp']>(
    async (input) => {
      const res = await authApi.register({ ...input, timezone: deviceTimezone() });
      await startSession(res, { id: res.caregiver.id, full_name: res.caregiver.full_name, email: input.email }, true);
    },
    [startSession],
  );

  const signInWithGoogle = useCallback<AuthContextValue['signInWithGoogle']>(async (remember) => {
    perfLoginStep('google_sign_in_started');
    const idToken = await getGoogleIdToken();
    if (!idToken) return false; // cancelled: silent
    perfLoginStep('google_sign_in_returned');

    const supabase = getSupabase();
    try {
      const { data, error } = await supabase.auth.signInWithIdToken({ provider: 'google', token: idToken });
      if (error || !data.session) throw new ApiError(401, 'GOOGLE_TOKEN_INVALID', error?.message ?? 'No session');
      perfLoginStep('supabase_session_ready');
      const res = await authApi.google({
        supabase_access_token: data.session.access_token,
        timezone: deviceTimezone(),
      });
      perfLoginStep('google_exchange_returned');
      await startSession(res, res.caregiver, remember);
      return true;
    } finally {
      // Never keep a second live session: ours is the only one.
      await supabase.auth.signOut({ scope: 'local' }).catch(() => undefined);
    }
  }, [startSession]);

  const signOut = useCallback(() => endSession(null), [endSession]);
  const clearSessionNotice = useCallback(() => setSessionNotice(null), []);

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
      sessionNotice,
      clearSessionNotice,
      signIn,
      signUp,
      signInWithGoogle,
      signOut,
      forgotPassword,
      resetPassword,
    }),
    [status, user, sessionNotice, clearSessionNotice, signIn, signUp, signInWithGoogle, signOut, forgotPassword, resetPassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
