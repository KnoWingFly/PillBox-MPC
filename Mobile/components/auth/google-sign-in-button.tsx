import { useState } from 'react';
import { TouchableOpacity, Text, Alert, ActivityIndicator, Image } from 'react-native';
import * as WebBrowser from 'expo-web-browser';
import * as Linking from 'expo-linking';
import { supabase } from '@root/utils/supabase';

WebBrowser.maybeCompleteAuthSession();

export default function GoogleSignInButton() {
  const [loading, setLoading] = useState(false);

  const handleGoogleSignIn = async () => {
    try {
      setLoading(true);
      
      const redirectUri = Linking.createURL('/auth/callback');

      const { data, error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: redirectUri,
          skipBrowserRedirect: true,
        },
      });

      if (error) throw error;

      if (data?.url) {
        const result = await WebBrowser.openAuthSessionAsync(data.url, redirectUri);

        if (result.type === 'success') {
          const { url } = result;
          const accessTokenMatch = url.match(/access_token=([^&]*)/);
          const refreshTokenMatch = url.match(/refresh_token=([^&]*)/);
          const codeMatch = url.match(/code=([^&]*)/);

          if (accessTokenMatch && refreshTokenMatch) {
            const { error: sessionError } = await supabase.auth.setSession({
              access_token: accessTokenMatch[1],
              refresh_token: refreshTokenMatch[1],
            });
            if (sessionError) throw sessionError;
          } else if (codeMatch && typeof supabase.auth.exchangeCodeForSession === 'function') {
            const { error: sessionError } = await supabase.auth.exchangeCodeForSession(codeMatch[1]);
            if (sessionError) throw sessionError;
          }
        }
      }
    } catch (err: any) {
      Alert.alert('Google Sign-In Error', err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <TouchableOpacity 
      onPress={handleGoogleSignIn}
      disabled={loading}
      className={`w-full bg-white border border-gray-300 rounded-xl py-3.5 flex-row items-center justify-center space-x-3 shadow-sm ${loading ? 'opacity-70' : 'opacity-100'}`}
    >
      {loading ? (
        <ActivityIndicator color="#4b5563" />
      ) : (
        <>
          <Image 
            source={{ uri: 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c1/Google_%22G%22_logo.svg/120px-Google_%22G%22_logo.svg.png' }}
            style={{ width: 24, height: 24 }}
            resizeMode="contain"
          />
          <Text className="text-gray-700 font-semibold text-lg ml-2">
            Continue with Google
          </Text>
        </>
      )}
    </TouchableOpacity>
  );
}