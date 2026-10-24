import { Pressable, Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';

import { Icon } from '../pillbox/ui';

/** Title bar for stack screens: back button and a centered title. */
export function BackHeader({ title, onBack }: { title: string; onBack: () => void }) {
  return (
    <View className="min-h-[56px] flex-row items-center gap-2 border-b border-line bg-surface px-2">
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={Strings.common.back}
        onPress={onBack}
        className="min-h-[44px] min-w-[44px] items-center justify-center rounded-full active:opacity-75">
        <Icon name="arrow-back" size={24} color={tokens.colors.ink.DEFAULT} />
      </Pressable>
      <Text className="flex-1 text-title font-bold text-ink" accessibilityRole="header" numberOfLines={1}>
        {title}
      </Text>
    </View>
  );
}
