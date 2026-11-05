import { router, type Href } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ONBOARDING_SLIDES } from '@/components/onboarding/slides';
import { Button } from '@/components/pillbox/ui';
import { BrandHeader } from '@/components/ui/brand-header';
import { LinkPrompt } from '@/components/ui/link-prompt';
import { PageDots } from '@/components/ui/page-dots';
import { Pager } from '@/components/ui/pager';
import { WideFrame } from '@/components/ui/wide-frame';
import { SecurityNote } from '@/components/ui/security-note';
import { Strings } from '@/constants/strings';
import { markOnboardingSeen } from '@/lib/onboarding';

const S = Strings.onboarding;
const LAST = ONBOARDING_SLIDES.length - 1;

// Leave onboarding for good: navigate first, then flag it, so the screen is gone before it reorders.
function finish(to: Href) {
  router.replace(to);
  markOnboardingSeen();
}

export default function OnboardingScreen() {
  const [index, setIndex] = useState(0);
  const last = index === LAST;

  return (
    <SafeAreaView className="flex-1 bg-surface xl:bg-canvas">
      <WideFrame>
        <View className="w-full max-w-[560px] flex-1 self-center md:max-w-[720px] lg:max-w-[1200px] xl:max-w-none xl:py-4">
          <View className="px-4 pb-3 md:px-8 lg:px-12 lg:pt-4 xl:px-16">
            <BrandHeader
              right={
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={S.skip}
                  onPress={() => finish('/auth/login')}
                  className="min-h-[44px] items-center justify-center rounded-full bg-primary-light px-4 active:opacity-75">
                  <Text className="text-body-sm font-semibold text-primary-dark">{S.skip}</Text>
                </Pressable>
              }
            />
          </View>

          <Pager pages={ONBOARDING_SLIDES} index={index} onIndexChange={setIndex} />

          {/* Phones: one centered column. From lg: one row (dots left, link + button right) to save height. */}
          <View className="w-full max-w-[480px] gap-3 self-center px-4 pb-4 pt-3 lg:max-w-none lg:px-12 xl:px-16">
            <View className="gap-3 lg:flex-row lg:items-center lg:justify-between">
              <PageDots count={ONBOARDING_SLIDES.length} index={index} onSelect={setIndex} />
              <View className="gap-3 lg:flex-row-reverse lg:items-center lg:gap-6">
                <View className="lg:min-w-[300px]">
                  <Button
                    label={last ? S.start : S.next}
                    icon="arrow-forward"
                    onPress={() => (last ? finish('/auth/register') : setIndex(index + 1))}
                  />
                </View>
                <LinkPrompt question={S.haveAccount} link={S.signInLink} onPress={() => finish('/auth/login')} />
              </View>
            </View>
            <SecurityNote text={Strings.brand.securityNote} />
          </View>
        </View>
      </WideFrame>
    </SafeAreaView>
  );
}
