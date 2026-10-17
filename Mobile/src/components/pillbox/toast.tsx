import { useEffect, useState } from 'react';
import { Animated, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import * as tokens from '@/theme/tokens';

import type { ToastTone } from './helpers';
import { Icon, type IconName } from './ui';

const TOAST_DURATION_MS = 3000;

export type ToastData = { id: number; text: string; tone: ToastTone };

const LOOK: Record<ToastTone, { box: string; icon: IconName }> = {
  success: { box: 'bg-ontime-solid', icon: 'checkmark-circle' },
  info: { box: 'bg-primary', icon: 'information-circle' },
  warning: { box: 'bg-late-solid', icon: 'warning' },
  error: { box: 'bg-missed-solid', icon: 'alert-circle' },
};

let toastSeq = 0;
export function makeToast(text: string, tone: ToastTone): ToastData {
  toastSeq += 1;
  return { id: toastSeq, text, tone };
}

export function Toast({ toast, onDone }: { toast: ToastData; onDone: (id: number) => void }) {
  const insets = useSafeAreaInsets();
  const [progress] = useState(() => new Animated.Value(0));

  useEffect(() => {
    const animation = Animated.sequence([
      Animated.timing(progress, { toValue: 1, duration: 220, useNativeDriver: true }),
      Animated.delay(TOAST_DURATION_MS - 440),
      Animated.timing(progress, { toValue: 0, duration: 220, useNativeDriver: true }),
    ]);
    animation.start(({ finished }) => {
      if (finished) onDone(toast.id);
    });
    return () => animation.stop();
  }, [progress, onDone, toast.id]);

  const translateY = progress.interpolate({ inputRange: [0, 1], outputRange: [-120, 0] });
  const look = LOOK[toast.tone];

  return (
    <Animated.View
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
      style={{
        position: 'absolute',
        top: insets.top + 8,
        left: 16,
        right: 16,
        zIndex: 50,
        elevation: 8,
        opacity: progress,
        transform: [{ translateY }],
        pointerEvents: 'none',
      }}>
      <View className={`flex-row items-center gap-3 rounded-2xl px-4 py-3.5 ${look.box}`} style={{ boxShadow: tokens.shadow.raised }}>
        <Icon name={look.icon} size={22} color="#FFFFFF" />
        <Text className="flex-1 text-body font-semibold text-white">{toast.text}</Text>
      </View>
    </Animated.View>
  );
}
