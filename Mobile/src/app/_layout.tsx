import { Stack } from 'expo-router';
import AuthProvider, { useAuthContext } from '@root/context/auth-context';
import '@root/global.css';

function RootNavigator() {
  const { isLoggedIn, isLoading } = useAuthContext();
  if (isLoading) return null; // swap for a splash/loading component

  return (
    <Stack>
      <Stack.Protected guard={isLoggedIn}>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      </Stack.Protected>
      <Stack.Protected guard={!isLoggedIn}>
        <Stack.Screen name="login" options={{ headerShown: false }} />
      </Stack.Protected>
    </Stack>
  );
}

export default function RootLayout() {
  return (
    <AuthProvider>
      <RootNavigator />
    </AuthProvider>
  );
}