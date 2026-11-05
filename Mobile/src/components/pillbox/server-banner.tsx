import { Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';

import { Button, Icon } from './ui';

/**
 * Shown above the dashboard while the backend cannot be reached, so a failed poll is not mistaken
 * for a pillbox problem (the pillbox itself may be fine).
 */
export function ServerBanner({ onRetry, retrying }: { onRetry: () => void; retrying: boolean }) {
  return (
    <View className="flex-row items-center gap-2 bg-missed-soft px-4 py-2" accessibilityRole="alert" accessibilityLiveRegion="polite">
      <Icon name="cloud-offline-outline" size={18} color={tokens.colors.missed.fg} />
      <Text className="flex-1 text-body-sm font-semibold text-missed-fg">{Strings.serverBanner.offline}</Text>
      <Button label={Strings.serverBanner.retry} variant="danger-soft" size="sm" onPress={onRetry} loading={retrying} />
    </View>
  );
}
