import type { ReactNode } from 'react';
import { View } from 'react-native';

import * as tokens from '@/theme/tokens';

/**
 * Full-bleed page on phones, tablets and small laptops. From the `xl` breakpoint the page becomes a
 * centered card with a maximum size on a tinted background, so content does not spread thin across
 * a large monitor.
 */
export function WideFrame({ children }: { children: ReactNode }) {
  return (
    <View className="flex-1 bg-surface xl:items-center xl:justify-center xl:bg-canvas xl:p-8">
      <View
        className="w-full flex-1 bg-surface xl:max-h-[1000px] xl:max-w-[1360px] xl:overflow-hidden xl:rounded-3xl 2xl:max-w-[1480px]"
        style={{ boxShadow: tokens.shadow.raised }}>
        {children}
      </View>
    </View>
  );
}
