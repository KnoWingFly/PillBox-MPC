import { Link } from 'expo-router';
import { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import FormField from '@root/components/auth/form-field';
import GoogleSignInButton from '@root/components/auth/google-sign-in-button';
import { Strings } from '@/constants/strings';
import { useAuth } from '@/hooks/use-auth';
import { errorMessage } from '@/lib/api/error-message';

type Mode = 'signIn' | 'signUp';
const E164 = /^\+[1-9]\d{6,14}$/;

export default function LoginScreen() {
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState<Mode>('signIn');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const t = Strings.auth;

  function validate(): string | null {
    if (!email.trim() || !password) return Strings.validation.required;
    if (mode === 'signIn') return null;
    if (!fullName.trim() || !phoneNumber.trim()) return Strings.validation.required;
    if (!E164.test(phoneNumber.trim())) return Strings.validation.phoneFormat;
    if (password.length < 8) return Strings.validation.passwordTooShort;
    if (password !== confirmPassword) return Strings.validation.passwordMismatch;
    return null;
  }

  async function onSubmit() {
    const problem = validate();
    if (problem) return Alert.alert(Strings.common.error, problem);

    setLoading(true);
    try {
      if (mode === 'signIn') await signIn(email.trim(), password);
      else
        await signUp({
          full_name: fullName.trim(),
          email: email.trim(),
          phone_number: phoneNumber.trim(),
          password,
        });
      // On success the auth gate swaps this screen out.
    } catch (err) {
      Alert.alert(Strings.common.error, errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  function switchMode(next: Mode) {
    setMode(next);
    setConfirmPassword('');
  }

  return (
    <SafeAreaView className="flex-1 bg-white">
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} className="flex-1">
        <ScrollView contentContainerClassName="flex-grow justify-center px-6 py-8" keyboardShouldPersistTaps="handled">
          <View className="mb-8 items-center">
            <View className="h-16 w-16 bg-blue-500 rounded-2xl items-center justify-center mb-4">
              <Text className="text-white text-3xl font-bold">P</Text>
            </View>
            <Text className="text-3xl font-bold text-gray-900 mb-2 text-center">{t.welcome}</Text>
            <Text className="text-gray-500 text-center">
              {mode === 'signIn' ? t.signInSubtitle : t.signUpSubtitle}
            </Text>
          </View>

          {/* Segmented control: Daftar | Masuk */}
          <View className="flex-row bg-gray-100 rounded-xl p-1 mb-6">
            {(['signUp', 'signIn'] as const).map((m) => (
              <TouchableOpacity
                key={m}
                onPress={() => switchMode(m)}
                disabled={loading}
                accessibilityRole="tab"
                accessibilityState={{ selected: mode === m }}
                // Keep the class list structurally identical between states: toggling classes that use
                // CSS variables (e.g. shadow-*) at runtime crashes NativeWind's component upgrade.
                className={`flex-1 py-2.5 rounded-lg items-center border ${mode === m ? 'bg-white border-gray-200' : 'bg-transparent border-transparent'}`}>
                <Text className={`font-semibold ${mode === m ? 'text-gray-900' : 'text-gray-500'}`}>
                  {m === 'signUp' ? t.tabSignUp : t.tabSignIn}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {mode === 'signUp' && (
            <FormField
              label={t.fullName}
              placeholder={t.fullNamePlaceholder}
              autoCapitalize="words"
              autoComplete="name"
              value={fullName}
              onChangeText={setFullName}
              editable={!loading}
            />
          )}
          <FormField
            label={t.email}
            placeholder={t.emailPlaceholder}
            autoCapitalize="none"
            keyboardType="email-address"
            autoComplete="email"
            value={email}
            onChangeText={setEmail}
            editable={!loading}
          />
          {mode === 'signUp' && (
            <FormField
              label={t.phoneNumber}
              placeholder={t.phoneNumberPlaceholder}
              keyboardType="phone-pad"
              autoComplete="tel"
              value={phoneNumber}
              onChangeText={setPhoneNumber}
              editable={!loading}
            />
          )}
          <FormField
            label={t.password}
            placeholder={t.passwordPlaceholder}
            secureToggle
            autoCapitalize="none"
            autoComplete={mode === 'signIn' ? 'current-password' : 'new-password'}
            value={password}
            onChangeText={setPassword}
            editable={!loading}
          />
          {mode === 'signUp' && (
            <FormField
              label={t.confirmPassword}
              placeholder={t.confirmPasswordPlaceholder}
              secureToggle
              autoCapitalize="none"
              autoComplete="new-password"
              value={confirmPassword}
              onChangeText={setConfirmPassword}
              editable={!loading}
            />
          )}

          {mode === 'signIn' && (
            <Link href="/auth/forgot-password" asChild>
              <TouchableOpacity className="self-end mb-2" disabled={loading}>
                <Text className="text-sm font-medium text-blue-600">{t.forgotPasswordLink}</Text>
              </TouchableOpacity>
            </Link>
          )}

          <TouchableOpacity
            onPress={onSubmit}
            disabled={loading}
            className={`w-full bg-blue-600 rounded-xl py-4 items-center justify-center mt-2 ${loading ? 'opacity-70' : ''}`}>
            {loading ? (
              <ActivityIndicator color="white" />
            ) : (
              <Text className="text-white font-semibold text-lg">
                {mode === 'signIn' ? t.submitSignIn : t.submitSignUp}
              </Text>
            )}
          </TouchableOpacity>

          <View className="flex-row items-center my-6">
            <View className="flex-1 h-[1px] bg-gray-200" />
            <Text className="mx-4 text-gray-500 font-medium">{t.or}</Text>
            <View className="flex-1 h-[1px] bg-gray-200" />
          </View>

          <GoogleSignInButton disabled={loading} />
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
