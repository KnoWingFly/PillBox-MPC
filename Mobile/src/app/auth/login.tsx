import { Link, router } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import AuthScreen from '@root/components/auth/auth-screen';
import CheckboxRow from '@root/components/auth/checkbox-row';
import FormField from '@root/components/auth/form-field';
import GoogleSignInButton from '@root/components/auth/google-sign-in-button';
import LegalLine from '@root/components/auth/legal-line';
import SessionNotice from '@root/components/auth/session-notice';
import { Button } from '@/components/pillbox/ui';
import { DividerLabel } from '@/components/ui/divider-label';
import { LinkPrompt } from '@/components/ui/link-prompt';
import { SecurityNote } from '@/components/ui/security-note';
import { AppConfig } from '@/config';
import { Strings } from '@/constants/strings';
import { useAuth } from '@/hooks/use-auth';
import { useAuthSubmit } from '@/hooks/use-auth-submit';
import { validateSignIn } from '@/lib/auth-form';
import { resetOnboarding } from '@/lib/onboarding';

const S = Strings.signIn;

function replayOnboarding() {
  resetOnboarding();
  router.replace('/onboarding');
}

export default function LoginScreen() {
  const { signIn, sessionNotice } = useAuth();
  const { loading, submit } = useAuthSubmit();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(true);

  const onSubmit = () =>
    submit(validateSignIn({ email, password }), () => signIn(email.trim(), password, remember));

  return (
    <AuthScreen title={S.title} subtitle={S.subtitle}>
      {sessionNotice && <SessionNotice text={sessionNotice} />}

      <FormField
        label={S.email}
        icon="mail-outline"
        placeholder={S.emailPlaceholder}
        autoCapitalize="none"
        keyboardType="email-address"
        autoComplete="email"
        value={email}
        onChangeText={setEmail}
        editable={!loading}
      />
      <FormField
        label={S.password}
        icon="lock-closed-outline"
        placeholder={S.passwordPlaceholder}
        secureToggle
        autoCapitalize="none"
        autoComplete="current-password"
        value={password}
        onChangeText={setPassword}
        editable={!loading}
        onSubmitEditing={onSubmit}
      />

      <View className="mb-4 flex-row items-center justify-between gap-2">
        <CheckboxRow
          checked={remember}
          onToggle={() => setRemember((v) => !v)}
          disabled={loading}
          label={<Text className="text-body-sm text-ink">{Strings.auth.rememberMe}</Text>}
          accessibilityLabel={Strings.auth.rememberMe}
          accessibilityHint={Strings.auth.rememberMeHint}
        />
        <Link href="/auth/forgot-password" asChild>
          <Pressable disabled={loading} accessibilityRole="link" className="min-h-[44px] justify-center active:opacity-75">
            <Text className="text-body-sm font-bold text-primary">{S.forgotPassword}</Text>
          </Pressable>
        </Link>
      </View>

      <View className="gap-5">
        <Button label={S.submit} onPress={onSubmit} loading={loading} />
        <DividerLabel label={S.divider} />
        <GoogleSignInButton disabled={loading} remember={remember} />
        <LinkPrompt question={S.noAccount} link={S.signUpLink} onPress={() => router.push('/auth/register')} />
        <SecurityNote text={S.encrypted} />
        <LegalLine
          centered
          parts={{ prefix: S.legalPrefix, terms: S.terms, join: S.legalJoin, privacy: S.privacy, suffix: S.legalSuffix }}
        />
        {AppConfig.showDebugTools && (
          <Button label={S.debugOnboarding} icon="bug-outline" variant="secondary" size="sm" onPress={replayOnboarding} />
        )}
      </View>
    </AuthScreen>
  );
}
