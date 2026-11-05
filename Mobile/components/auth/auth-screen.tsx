import type { ReactNode } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { BrandHeader } from '@/components/ui/brand-header';
import { WideFrame } from '@/components/ui/wide-frame';
import { useMinWidth } from '@/hooks/use-breakpoint';

import AuthAside from './auth-aside';

/**
 * Page frame shared by Masuk and Buat Akun: brand header, optional badge, title, subtitle, then the
 * form. Phones get one centered column; from `lg` a brand panel sits on the left and the form on the
 * right; from `xl` both sit in a centered card (WideFrame).
 */
export default function AuthScreen({ badge, title, subtitle, children }: {
  badge?: ReactNode;
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  // Mounted only when visible: hiding it with classes would still run its animation on phones.
  const wide = useMinWidth('lg');

  return (
    <SafeAreaView className="flex-1 bg-surface xl:bg-canvas">
      <WideFrame>
        <View className="flex-1 flex-row">
          {wide && <AuthAside />}
          <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} className="flex-1">
            <ScrollView
              contentContainerClassName="w-full max-w-[560px] flex-grow self-center px-4 pb-8 md:px-8 md:pt-6 lg:max-w-[520px] lg:justify-center lg:py-12 xl:py-8 2xl:max-w-[560px]"
              keyboardShouldPersistTaps="handled">
              <BrandHeader />
              <View className="mb-6 mt-4 gap-2">
                {badge}
                <Text className="text-display font-bold tracking-tight text-ink 2xl:text-hero" accessibilityRole="header">
                  {title}
                </Text>
                <Text className="text-body-sm text-ink-muted 2xl:text-body">{subtitle}</Text>
              </View>
              {children}
            </ScrollView>
          </KeyboardAvoidingView>
        </View>
      </WideFrame>
    </SafeAreaView>
  );
}
