import { useState } from 'react';
import { ActivityIndicator, Alert, Image, Platform, Text, TouchableOpacity, View } from 'react-native';

import { Strings } from '@/constants/strings';
import { useAuth } from '@/hooks/use-auth';
import { errorMessage } from '@/lib/api/error-message';
import { getGoogleSignInUnavailableMessage } from '@/lib/google-signin';
import * as tokens from '@/theme/tokens';

// Bundled, so the button never depends on a third-party host (offline, blocked, tracking).
const GOOGLE_LOGO = require('@/assets/images/google-g.png');
const GOOGLE_LOGO_SIZE = 24;

function googleSignInDebugDetails(err: unknown): string {
  const value = err && typeof err === 'object' ? (err as Record<string, unknown>) : {};
  const stage = typeof value.googleSignInStage === 'string' ? value.googleSignInStage : 'unknown';
  const code = typeof value.code === 'string' || typeof value.code === 'number' ? String(value.code) : '';
  const status = typeof value.status === 'number' ? String(value.status) : '';
  const rawReason = err instanceof Error ? err.message : String(err);
  const reason = rawReason
    .replace(/\bBearer\s+\S+/gi, 'Bearer [redacted]')
    .replace(/\beyJ[\w-]*\.[\w-]*\.[\w-]*\b/g, '[redacted token]')
    .replace(/\b(access_token|id_token|refresh_token)\s*[:=]\s*[^,\s]+/gi, '$1=[redacted]')
    .slice(0, 180);
  const webClientId = process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID?.trim();
  const clientIdPart = webClientId?.match(/-([^-]+)\.apps\.googleusercontent\.com$/)?.[1];
  const clientIdSuffix = clientIdPart ? clientIdPart.slice(-8) : webClientId ? 'format-invalid' : 'missing';
  return Strings.auth.googleDebugDetails(stage, code, status, reason, clientIdSuffix);
}

export default function GoogleSignInButton({
  disabled,
  remember = true,
  label = Strings.auth.continueWithGoogle,
  onError,
}: {
  disabled?: boolean;
  remember?: boolean;
  label?: string;
  /** Shows a failed sign-in (the screen's toast; Alert.alert does nothing on web). */
  onError: (message: string) => void;
}) {
  const { signInWithGoogle, clearSessionNotice } = useAuth();
  const [loading, setLoading] = useState(false);
  const unavailableMessage = getGoogleSignInUnavailableMessage();

  const onPress = async () => {
    if (loading) return;
    setLoading(true);
    try {
      clearSessionNotice();
      await signInWithGoogle(remember); // false = cancelled, stays silent
    } catch (err) {
      const message = errorMessage(err);
      if (__DEV__) {
        const details = googleSignInDebugDetails(err);
        if (Platform.OS === 'web') onError(`${message}\n${details}`);
        else Alert.alert(Strings.auth.googleDebugTitle, `${message}\n\n${details}`);
      } else {
        onError(message);
      }
    } finally {
      setLoading(false);
    }
  };

  // Keep the action tappable when setup detection fails so users see the actual sign-in error.
  const isDisabled = loading || disabled;

  return (
    <View>
      <TouchableOpacity
        onPress={onPress}
        disabled={isDisabled}
        accessibilityRole="button"
        accessibilityLabel={label}
        accessibilityState={{ disabled: isDisabled, busy: loading }}
        className={`min-h-[52px] w-full flex-row items-center justify-center gap-3 rounded-2xl border border-line bg-surface ${isDisabled ? 'opacity-50' : 'opacity-100'}`}
        style={{ boxShadow: tokens.shadow.card }}>
        {loading ? (
          <ActivityIndicator color={tokens.colors.ink.muted} />
        ) : (
          <>
            <Image
              source={GOOGLE_LOGO}
              style={{ width: GOOGLE_LOGO_SIZE, height: GOOGLE_LOGO_SIZE }}
              resizeMode="contain"
            />
            <Text className="text-body font-semibold text-ink">{label}</Text>
          </>
        )}
      </TouchableOpacity>
      {unavailableMessage && <Text className="mt-2 text-center text-caption text-ink-muted">{unavailableMessage}</Text>}
    </View>
  );
}
