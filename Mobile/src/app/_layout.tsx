import Ionicons from '@expo/vector-icons/Ionicons';
import { SplashScreen, Stack } from 'expo-router';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import AuthProvider from '@root/context/auth-context';
import { AppLoading } from '@/components/ui/app-loading';
import { useAuth } from '@/hooks/use-auth';
import '@root/global.css';
import { useOnboardingState } from '@/lib/onboarding';
import { perfLoginStep } from '@/lib/perf';

SplashScreen.preventAutoHideAsync();
perfLoginStep('app_start');

// Load the icon font once, before any icon mounts. On web, expo-font stops waiting after 12 s
// (slow first load after `expo start -c`, or the tab in the background) and rejects with
// "12000ms timeout exceeded", although the browser still finishes loading the font. Each icon
// awaits that same load without a catch, so the rejection showed up as a red error. Started here,
// the @font-face rule exists before the icons mount, so they treat the font as loaded.
Ionicons.loadFont().catch((err: unknown) => {
  if (__DEV__) console.info('[pillbox] icon font still loading:', err instanceof Error ? err.message : err);
});

// Keeps the native splash visible until the stored session and the onboarding flag have been read.
function SplashScreenController() {
  const { status } = useAuth();
  const onboarding = useOnboardingState();
  if (status !== 'loading' && onboarding !== 'loading') SplashScreen.hide();
  return null;
}

function RootNavigator() {
  const { status } = useAuth();
  const onboarding = useOnboardingState();
  if (status === 'loading' || onboarding === 'loading') return <AppLoading />;
  const signedIn = status === 'signedIn';
  // Signed out: onboarding until it was finished once on this phone, then Masuk. Onboarding stays
  // reachable afterwards (the debug button on Masuk opens it).
  const signedOutHome = onboarding === 'unseen' ? '/onboarding' : '/auth/login';

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Protected guard={signedIn} redirectTo={signedOutHome}>
        <Stack.Screen name="index" />
        <Stack.Screen name="explore" />
        <Stack.Screen name="elderly/new" />
        <Stack.Screen name="elderly/[id]/schedule" />
      </Stack.Protected>
      <Stack.Protected guard={!signedIn} redirectTo="/">
        <Stack.Screen name="onboarding" />
        <Stack.Screen name="auth/login" />
        <Stack.Screen name="auth/register" />
        <Stack.Screen name="auth/forgot-password" />
        <Stack.Screen name="auth/reset-password" />
      </Stack.Protected>
    </Stack>
  );
}

export default function RootLayout() {
  return (
    // Required by react-native-gesture-handler (swipe-to-delete on notifications).
    <GestureHandlerRootView style={{ flex: 1 }}>
      <AuthProvider>
        <SplashScreenController />
        <RootNavigator />
      </AuthProvider>
    </GestureHandlerRootView>
  );
}
