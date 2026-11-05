import { router } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import AuthScreen from '@root/components/auth/auth-screen';
import CheckboxRow from '@root/components/auth/checkbox-row';
import FormField from '@root/components/auth/form-field';
import GoogleSignInButton from '@root/components/auth/google-sign-in-button';
import LegalLine from '@root/components/auth/legal-line';
import PasswordStrengthMeter from '@root/components/auth/password-strength-meter';
import { Button, StatusPill } from '@/components/pillbox/ui';
import { DividerLabel } from '@/components/ui/divider-label';
import { LinkPrompt } from '@/components/ui/link-prompt';
import { SecurityNote } from '@/components/ui/security-note';
import { AppConfig } from '@/config';
import { Strings } from '@/constants/strings';
import { useAuth } from '@/hooks/use-auth';
import { useAuthSubmit } from '@/hooks/use-auth-submit';
import { EMPTY_SIGN_UP, toRegisterInput, validateSignUp, type SignUpValues } from '@/lib/auth-form';

const S = Strings.signUp;
const CONSENT = { prefix: S.consentPrefix, terms: S.terms, join: S.consentJoin, privacy: S.privacy, suffix: S.consentSuffix };

// Back to Masuk: pop when we came from there, otherwise (straight from onboarding) replace.
function goToSignIn() {
  if (router.canGoBack()) router.back();
  else router.replace('/auth/login');
}

export default function RegisterScreen() {
  const { signUp } = useAuth();
  const { loading, submit, showToast, toastNode } = useAuthSubmit();
  const [values, setValues] = useState<SignUpValues>(EMPTY_SIGN_UP);
  const set = <K extends keyof SignUpValues>(key: K) => (value: SignUpValues[K]) =>
    setValues((v) => ({ ...v, [key]: value }));

  const onSubmit = () => submit(validateSignUp(values), () => signUp(toRegisterInput(values)));

  return (
    <AuthScreen
      badge={<View className="self-start"><StatusPill label={S.badge} tone="primary" icon="shield-checkmark-outline" /></View>}
      title={S.title}
      subtitle={S.subtitle}
      overlay={toastNode}>
      <FormField
        label={S.fullName}
        labelRight={<Text className="text-caption text-ink-muted">{S.fullNameHint}</Text>}
        icon="person-outline"
        placeholder={S.fullNamePlaceholder}
        autoCapitalize="words"
        autoComplete="name"
        value={values.fullName}
        onChangeText={set('fullName')}
        editable={!loading}
      />
      <FormField
        label={S.email}
        icon="mail-outline"
        placeholder={S.emailPlaceholder}
        autoCapitalize="none"
        keyboardType="email-address"
        autoComplete="email"
        value={values.email}
        onChangeText={set('email')}
        editable={!loading}
      />
      <FormField
        label={S.phone}
        labelRight={<StatusPill label={S.phoneBadge} tone="ontime" />}
        prefix={`+${AppConfig.phoneCountryCode}`}
        placeholder={S.phonePlaceholder}
        keyboardType="phone-pad"
        autoComplete="tel-national"
        value={values.phone}
        onChangeText={set('phone')}
        editable={!loading}
      />
      <FormField
        label={S.password}
        icon="lock-closed-outline"
        placeholder={S.passwordPlaceholder(AppConfig.passwordMinLength)}
        secureToggle
        autoCapitalize="none"
        autoComplete="new-password"
        maxLength={AppConfig.passwordMaxLength}
        value={values.password}
        onChangeText={set('password')}
        editable={!loading}
        footer={<PasswordStrengthMeter password={values.password} />}
      />
      <FormField
        label={S.confirmPassword}
        icon="refresh-outline"
        placeholder={S.confirmPasswordPlaceholder}
        secureToggle
        autoCapitalize="none"
        autoComplete="new-password"
        maxLength={AppConfig.passwordMaxLength}
        value={values.confirmPassword}
        onChangeText={set('confirmPassword')}
        editable={!loading}
      />

      <View className="mb-5">
        <CheckboxRow
          checked={values.consent}
          onToggle={() => set('consent')(!values.consent)}
          disabled={loading}
          label={<LegalLine parts={CONSENT} />}
          accessibilityLabel={S.consentA11y}
        />
      </View>

      <View className="gap-5">
        <Button label={S.submit} icon="arrow-forward" onPress={onSubmit} loading={loading} />
        <DividerLabel label={S.divider} />
        <GoogleSignInButton onError={(message) => showToast(message, 'error')} disabled={loading} label={S.google} />
        <LinkPrompt question={S.haveAccount} link={S.signInLink} onPress={goToSignIn} />
        <SecurityNote text={Strings.brand.securityNote} boxed />
        <Text className="text-center text-caption text-ink-muted">{S.privacyNote}</Text>
      </View>
    </AuthScreen>
  );
}
