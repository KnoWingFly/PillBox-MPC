import { router, useLocalSearchParams } from 'expo-router';
import { useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import FormField from '@root/components/auth/form-field';
import SessionNotice from '@root/components/auth/session-notice';
import { Dialog, DialogHeader } from '@/components/pillbox/dialog';
import { Button } from '@/components/pillbox/ui';
import { Strings } from '@/constants/strings';
import { useAuth } from '@/hooks/use-auth';
import { useToast } from '@/hooks/use-toast';
import { errorMessage } from '@/lib/api/error-message';
import { newPasswordProblem } from '@/lib/password-strength';

const OTP_PATTERN = /^\d{6}$/;
const goToSignIn = () => router.dismissTo('/auth/login');

export default function ResetPasswordScreen() {
  const { resetPassword } = useAuth();
  const params = useLocalSearchParams<{ email?: string; sent?: string }>();
  const [email, setEmail] = useState(params.email ?? '');
  const [otp, setOtp] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const inFlight = useRef(false);
  const { showToast, toastNode } = useToast();
  const t = Strings.resetPassword;

  function problem(): string | null {
    if (!email.trim() || !otp || !newPassword) return Strings.validation.required;
    if (!OTP_PATTERN.test(otp)) return Strings.validation.otpFormat;
    const passwordProblem = newPasswordProblem(newPassword);
    if (passwordProblem) return passwordProblem;
    if (newPassword !== confirmPassword) return Strings.validation.passwordMismatch;
    return null;
  }

  async function onSubmit() {
    const invalid = problem();
    if (invalid) return showToast(invalid, 'error');
    if (inFlight.current) return;

    inFlight.current = true;
    setLoading(true);
    try {
      await resetPassword(email.trim(), otp, newPassword);
      setDone(true);
    } catch (err) {
      showToast(errorMessage(err), 'error');
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }

  return (
    <SafeAreaView className="flex-1 bg-white">
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} className="flex-1 justify-center px-6">
        <Text className="text-3xl font-bold text-gray-900 mb-2">{t.title}</Text>
        <Text className="text-gray-500 mb-8">{t.subtitle}</Text>
        {params.sent ? <SessionNotice text={Strings.forgotPassword.sentMessage} /> : null}

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
          <TouchableOpacity onPress={goToSignIn} disabled={loading}>
            <Text className="font-semibold text-blue-600">{Strings.forgotPassword.backToSignIn}</Text>
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
      <Dialog visible={done} onCancel={goToSignIn}>
        <DialogHeader icon="checkmark-circle-outline" tone="success" title={t.successTitle} message={t.successMessage} />
        <Button label={Strings.common.ok} variant="success" onPress={goToSignIn} />
      </Dialog>
      {toastNode}
    </SafeAreaView>
  );
}
