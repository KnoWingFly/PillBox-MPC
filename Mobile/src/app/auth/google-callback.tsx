import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Text, View } from 'react-native';

import AuthScreen from '@root/components/auth/auth-screen';
import { Button } from '@/components/pillbox/ui';
import { Strings } from '@/constants/strings';
import { useAuth } from '@/hooks/use-auth';
import { errorMessage } from '@/lib/api/error-message';

export default function GoogleCallbackScreen() {
  const { completeGoogleSignIn } = useAuth();
  const { code, error, remember } = useLocalSearchParams<{ code?: string; error?: string; remember?: string }>();
  const [failure, setFailure] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    if (error || !code) {
      setFailure(Strings.auth.googleCallbackError);
      return;
    }
    void completeGoogleSignIn(code, remember !== 'false').catch((err: unknown) => setFailure(errorMessage(err)));
  }, [code, completeGoogleSignIn, error, remember]);

  return (
    <AuthScreen
      title={Strings.auth.googleCallbackTitle}
      subtitle={failure ? Strings.auth.googleCallbackError : Strings.auth.googleCallbackSubtitle}>
      {failure && (
        <View className="gap-4">
          <Text className="text-center text-body-sm text-danger">{failure}</Text>
          <Button label={Strings.auth.googleCallbackBack} onPress={() => router.replace('/auth/login')} />
        </View>
      )}
    </AuthScreen>
  );
}
