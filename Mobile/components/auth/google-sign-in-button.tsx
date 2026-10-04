import { useState } from 'react';
import { ActivityIndicator, Alert, Image, Text, TouchableOpacity, View } from 'react-native';

import { Strings } from '@/constants/strings';
import { useAuth } from '@/hooks/use-auth';
import { errorMessage } from '@/lib/api/error-message';
import { isGoogleSignInAvailable } from '@/lib/google-signin';

export default function GoogleSignInButton({ disabled }: { disabled?: boolean }) {
  const { signInWithGoogle } = useAuth();
  const [loading, setLoading] = useState(false);
  const available = isGoogleSignInAvailable();

  const onPress = async () => {
    setLoading(true);
    try {
      await signInWithGoogle(); // false = cancelled, stays silent
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
        className={`w-full bg-white border border-gray-300 rounded-xl py-3.5 flex-row items-center justify-center shadow-sm ${isDisabled ? 'opacity-50' : 'opacity-100'}`}>
        {loading ? (
          <ActivityIndicator color="#4b5563" />
        ) : (
          <>
            <Image
              source={{ uri: 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c1/Google_%22G%22_logo.svg/120px-Google_%22G%22_logo.svg.png' }}
              style={{ width: 24, height: 24 }}
              resizeMode="contain"
            />
            <Text className="text-gray-700 font-semibold text-lg ml-2">{Strings.auth.continueWithGoogle}</Text>
          </>
        )}
      </TouchableOpacity>
      {!available && <Text className="text-xs text-gray-500 text-center mt-2">{Strings.auth.googleUnavailable}</Text>}
    </View>
  );
}
