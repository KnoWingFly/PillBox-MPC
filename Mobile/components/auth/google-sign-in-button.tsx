import { useState } from 'react';
import { ActivityIndicator, Alert, Image, Text, TouchableOpacity, View } from 'react-native';

import { Strings } from '@/constants/strings';
import { useAuth } from '@/hooks/use-auth';
import { errorMessage } from '@/lib/api/error-message';
import { isGoogleSignInAvailable } from '@/lib/google-signin';
import * as tokens from '@/theme/tokens';

const GOOGLE_LOGO_URI = 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c1/Google_%22G%22_logo.svg/120px-Google_%22G%22_logo.svg.png';
const GOOGLE_LOGO_SIZE = 24;

export default function GoogleSignInButton({
  disabled,
  remember = true,
  label = Strings.auth.continueWithGoogle,
}: {
  disabled?: boolean;
  remember?: boolean;
  label?: string;
}) {
  const { signInWithGoogle, clearSessionNotice } = useAuth();
  const [loading, setLoading] = useState(false);
  const available = isGoogleSignInAvailable();

  const onPress = async () => {
    setLoading(true);
    try {
      clearSessionNotice();
      await signInWithGoogle(remember); // false = cancelled, stays silent
    } catch (err) {
      Alert.alert(Strings.common.error, errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const isDisabled = !available || loading || disabled;

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
              source={{ uri: GOOGLE_LOGO_URI }}
              style={{ width: GOOGLE_LOGO_SIZE, height: GOOGLE_LOGO_SIZE }}
              resizeMode="contain"
            />
            <Text className="text-body font-semibold text-ink">{label}</Text>
          </>
        )}
      </TouchableOpacity>
      {!available && <Text className="mt-2 text-center text-caption text-ink-muted">{Strings.auth.googleUnavailable}</Text>}
    </View>
  );
}
