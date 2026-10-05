import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import FormField from '@root/components/auth/form-field';
import { Strings } from '@/constants/strings';
import { useAuth } from '@/hooks/use-auth';
import { errorMessage } from '@/lib/api/error-message';

export default function ResetPasswordScreen() {
  const { resetPassword } = useAuth();
  const params = useLocalSearchParams<{ email?: string }>();
  const [email, setEmail] = useState(params.email ?? '');
  const [otp, setOtp] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const t = Strings.resetPassword;

  async function onSubmit() {
    if (!email.trim() || !otp || !newPassword) return Alert.alert(Strings.common.error, Strings.validation.required);
    if (!/^\d{6}$/.test(otp)) return Alert.alert(Strings.common.error, Strings.validation.otpFormat);
    if (newPassword.length < 8) return Alert.alert(Strings.common.error, Strings.validation.passwordTooShort);
    if (newPassword !== confirmPassword) return Alert.alert(Strings.common.error, Strings.validation.passwordMismatch);

    setLoading(true);
    try {
      await resetPassword(email.trim(), otp, newPassword);
      Alert.alert(t.successTitle, t.successMessage, [
        { text: Strings.common.ok, onPress: () => router.dismissTo('/auth/login') },
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
          value={email}
          onChangeText={setEmail}
          editable={!loading}
        />
        <FormField
          label={t.otp}
          placeholder={t.otpPlaceholder}
          keyboardType="number-pad"
          autoComplete="one-time-code"
          maxLength={6}
          value={otp}
          onChangeText={(v) => setOtp(v.replace(/\D/g, ''))}
          editable={!loading}
        />
        <FormField
          label={t.newPassword}
          placeholder={Strings.auth.passwordPlaceholder}
          secureToggle
          autoCapitalize="none"
          autoComplete="new-password"
          value={newPassword}
          onChangeText={setNewPassword}
          editable={!loading}
        />
        <FormField
          label={Strings.auth.confirmPassword}
          placeholder={Strings.auth.confirmPasswordPlaceholder}
          secureToggle
          autoCapitalize="none"
          autoComplete="new-password"
          value={confirmPassword}
          onChangeText={setConfirmPassword}
          editable={!loading}
        />

        <TouchableOpacity
          onPress={onSubmit}
          disabled={loading}
          className={`w-full bg-blue-600 rounded-xl py-4 items-center mt-2 ${loading ? 'opacity-70' : ''}`}>
          {loading ? <ActivityIndicator color="white" /> : <Text className="text-white font-semibold text-lg">{t.submit}</Text>}
        </TouchableOpacity>

        <View className="mt-6 items-center">
          <TouchableOpacity onPress={() => router.dismissTo('/auth/login')} disabled={loading}>
            <Text className="font-semibold text-blue-600">{Strings.forgotPassword.backToSignIn}</Text>
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
