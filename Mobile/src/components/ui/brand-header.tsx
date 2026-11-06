import type { ReactNode } from 'react';
import { Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';

import { Icon } from '../pillbox/ui';

/** PillCare logo, name and tagline, with an optional action on the right (e.g. "Lewati"). */
export function BrandHeader({ right }: { right?: ReactNode }) {
  return (
    <View className="min-h-[56px] flex-row items-center justify-between gap-3">
      <View className="flex-row items-center gap-3">
        <View
          className="h-12 w-12 items-center justify-center rounded-full bg-primary"
          accessible
          accessibilityRole="image"
          accessibilityLabel={Strings.brand.logoA11y}>
          <Icon name="medkit" size={24} color={tokens.colors.surface.DEFAULT} />
        </View>
        <View>
          <Text className="text-title font-bold text-ink">{Strings.brand.name}</Text>
          <Text className="text-caption text-ink-muted">{Strings.brand.tagline}</Text>
        </View>
      </View>
      {right}
    </View>
  );
}
