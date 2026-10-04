import { router } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import FormField from '@root/components/auth/form-field';
import { Strings } from '@/constants/strings';
import { useAuth } from '@/hooks/use-auth';
import { errorMessage } from '@/lib/api/error-message';

export default function ForgotPasswordScreen() {
  const { forgotPassword } = useAuth();
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const t = Strings.forgotPassword;

  async function onSubmit() {
    const trimmed = email.trim();
    if (!trimmed) return Alert.alert(Strings.common.error, Strings.validation.required);

    setLoading(true);
    try {
      await forgotPassword(trimmed);
      Alert.alert(t.sentTitle, t.sentMessage, [
        { text: Strings.common.ok, onPress: () => router.push({ pathname: '/auth/reset-password', params: { email: trimmed } }) },
      ]);
    } catch (err) {
      Alert.alert(Strings.common.error, errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <SafeAreaView className="flex-1 bg-white">
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} className="flex-1 justify-center px-6">
        <Text className="text-3xl font-bold text-gray-900 mb-2">{t.title}</Text>
        <Text className="text-gray-500 mb-8">{t.subtitle}</Text>

        <FormField
          label={Strings.auth.email}
          placeholder={Strings.auth.emailPlaceholder}
          autoCapitalize="none"
          keyboardType="email-address"
          autoComplete="email"
          value={email}
          onChangeText={setEmail}
          editable={!loading}
        />

        <TouchableOpacity
          onPress={onSubmit}
          disabled={loading}
          className={`w-full bg-blue-600 rounded-xl py-4 items-center ${loading ? 'opacity-70' : ''}`}>
          {loading ? <ActivityIndicator color="white" /> : <Text className="text-white font-semibold text-lg">{t.submit}</Text>}
        </TouchableOpacity>

        <View className="mt-6 items-center">
          <TouchableOpacity onPress={() => router.back()} disabled={loading}>
            <Text className="font-semibold text-blue-600">{t.backToSignIn}</Text>
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
