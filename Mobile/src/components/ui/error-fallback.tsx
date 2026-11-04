import type { ErrorBoundaryProps } from 'expo-router';
import { useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, IconBadge } from '@/components/pillbox/ui';
import { Strings } from '@/constants/strings';

/**
 * Shown by the root ErrorBoundary (src/app/_layout.tsx) when a screen throws while rendering,
 * instead of a blank screen (release) or the red box (development). "Muat Ulang" re-renders the
 * route. The technical message is only shown in development builds.
 */
export function ErrorFallback({ error, retry }: ErrorBoundaryProps) {
  const [retrying, setRetrying] = useState(false);
  const onRetry = async () => {
    setRetrying(true);
    try {
      await retry();
    } finally {
      setRetrying(false);
    }
  };
  return (
    <SafeAreaView className="flex-1 bg-canvas">
      <ScrollView contentContainerClassName="flex-grow items-center justify-center gap-4 px-6 py-8">
        <IconBadge icon="alert-circle-outline" tone="missed" size="lg" />
        <View className="items-center gap-2">
          <Text className="text-center text-heading font-bold text-ink" accessibilityRole="header">
            {Strings.crash.title}
          </Text>
          <Text className="text-center text-body text-ink-muted">{Strings.crash.text}</Text>
        </View>
        <View className="w-full max-w-[420px]">
          <Button label={Strings.crash.retry} icon="refresh" onPress={() => void onRetry()} loading={retrying} />
        </View>
        {__DEV__ && (
          <View className="w-full max-w-[420px] gap-1 rounded-2xl bg-surface-muted p-3">
            <Text className="text-caption font-semibold text-ink-muted">{Strings.crash.details}</Text>
            <Text className="text-caption text-ink-muted" selectable>
              {error.message}
            </Text>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
