import { SplashScreen, Stack } from 'expo-router';
import AuthProvider from '@root/context/auth-context';
import { useAuth } from '@/hooks/use-auth';
import '@root/global.css';

SplashScreen.preventAutoHideAsync();

// Keeps the native splash visible until the stored session has been restored.
function SplashScreenController() {
  const { status } = useAuth();
  if (status !== 'loading') SplashScreen.hide();
  return null;
}

function RootNavigator() {
  const { status } = useAuth();
  if (status === 'loading') return null;
  const signedIn = status === 'signedIn';

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Protected guard={signedIn}>
        <Stack.Screen name="index" />
        <Stack.Screen name="explore" />
      </Stack.Protected>
      <Stack.Protected guard={!signedIn}>
        <Stack.Screen name="auth/login" />
        <Stack.Screen name="auth/forgot-password" />
        <Stack.Screen name="auth/reset-password" />
      </Stack.Protected>
    </Stack>
  );
}

export default function RootLayout() {
  return (
    <AuthProvider>
      <SplashScreenController />
      <RootNavigator />
    </AuthProvider>
  );
}
