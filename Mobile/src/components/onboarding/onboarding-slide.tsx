import type { ReactNode } from 'react';
import { ScrollView, Text, View } from 'react-native';

import { StatusPill, type IconName } from '../pillbox/ui';

/**
 * One onboarding page: illustration, feature badge, headline and body. Stacked and scrollable on
 * phones; side by side (illustration left, text right) from the `lg` breakpoint.
 */
export function OnboardingSlide({ preview, badge, badgeIcon, title, body, centered = true }: {
  preview: ReactNode;
  badge: string;
  badgeIcon: IconName;
  title: string;
  body: string;
  centered?: boolean;
}) {
  const align = centered ? 'items-center lg:items-start' : 'items-start';
  const textAlign = centered ? 'text-center lg:text-left' : 'text-left';
  return (
    <ScrollView
      contentContainerClassName="flex-grow gap-5 px-4 pb-4 md:px-8 lg:flex-row lg:items-center lg:gap-12 lg:px-12 xl:gap-16 xl:px-16"
      showsVerticalScrollIndicator={false}>
      <View className="w-full max-w-[480px] self-center lg:flex-1 2xl:max-w-[560px]">{preview}</View>
      <View className={`w-full max-w-[560px] gap-3 self-center lg:flex-1 xl:gap-4 ${align}`}>
        <StatusPill label={badge} tone="primary" icon={badgeIcon} />
        <Text className={`text-display font-bold tracking-tight text-ink lg:text-hero ${textAlign}`} accessibilityRole="header">
          {title}
        </Text>
        <Text className={`text-body-sm text-ink-muted lg:text-body 2xl:text-title ${textAlign}`}>{body}</Text>
      </View>
    </ScrollView>
  );
}
