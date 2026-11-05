import { useEffect, useState } from 'react';
import { ActivityIndicator, Text, View } from 'react-native';

import { AppConfig } from '@/config';
import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';

import { Icon } from '../pillbox/ui';

/**
 * Shown while the app restores the session. On web the server renders it into the first HTML,
 * so the page is never blank while the JavaScript bundle downloads. After slowLoadingHintMs it
 * says that it is waiting for the server.
 */
export function AppLoading() {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), AppConfig.slowLoadingHintMs);
    return () => clearTimeout(timer);
  }, []);

  return (
    <View
      className="flex-1 items-center justify-center gap-4 bg-surface px-6"
      accessibilityRole="progressbar"
      accessibilityLabel={Strings.brand.loading}
      accessibilityState={{ busy: true }}>
      <View className="h-16 w-16 items-center justify-center rounded-full bg-primary">
        <Icon name="medkit" size={32} color={tokens.colors.surface.DEFAULT} />
      </View>
      <Text className="text-title font-bold text-ink">{Strings.brand.name}</Text>
      <ActivityIndicator size="large" color={tokens.colors.primary.DEFAULT} />
      <Text className="text-center text-body-sm text-ink-muted" accessibilityLiveRegion="polite">
        {slow ? Strings.brand.loadingSlow : Strings.brand.loading}
      </Text>
    </View>
  );
}
