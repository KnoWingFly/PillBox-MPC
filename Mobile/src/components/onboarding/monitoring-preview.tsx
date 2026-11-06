import { memo, useEffect } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Animated, {
  cancelAnimation,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';

import {
  ACTIVE_SLOT_PULSE_MS,
  ACTIVE_SLOT_PULSE_SCALE,
  DEMO_COMPLIANCE_RATIO,
  DEMO_SLOTS,
  type DemoSlotState,
} from '@/constants/onboarding';
import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';

import { Icon, IconBadge } from '../pillbox/ui';
import { PreviewCard, PreviewFrame, PreviewPill, ProgressBar } from './preview-parts';

const S = Strings.onboarding.monitoring;

/** Slide 1: pillbox status, the 8-slot tray and today's compliance. */
export function MonitoringPreview() {
  return (
    <PreviewFrame>
      <View className="flex-row items-center justify-between">
        <PreviewPill label={S.wifi} icon="wifi" dot />
        <PreviewPill label={S.battery} icon="battery-charging-outline" iconColor={tokens.colors.ontime.fg} />
      </View>

      <PreviewCard className="flex-row items-center">
        <IconBadge icon="person-outline" tone="primary" size="sm" />
        <View className="flex-1">
          <Text className="text-caption text-ink-muted">{S.registeredLabel}</Text>
          <Text className="text-body-sm font-bold text-ink">{S.registeredName}</Text>
        </View>
        <Icon name="shield-checkmark-outline" size={20} color={tokens.colors.ontime.fg} />
      </PreviewCard>

      <PreviewCard>
        <View className="flex-row items-center justify-between gap-2">
          <Text className="shrink text-caption font-bold uppercase text-ink-muted">{S.trayTitle}</Text>
          <Text className="text-caption font-bold text-primary">{S.activeSlot}</Text>
        </View>
        <View className="flex-row flex-wrap justify-between">
          {DEMO_SLOTS.map((slot) => (
            <DemoSlot key={slot.label} label={slot.label} time={slot.time} state={slot.state} />
          ))}
        </View>
      </PreviewCard>

      <PreviewCard>
        <View className="flex-row items-center justify-between gap-2">
          <View className="flex-row items-center gap-1.5">
            <Icon name="trending-up" size={16} color={tokens.colors.primary.DEFAULT} />
            <Text className="text-caption font-semibold text-ink">{S.complianceLabel}</Text>
          </View>
          <Text className="text-caption font-bold text-primary">{S.complianceValue}</Text>
        </View>
        <ProgressBar ratio={DEMO_COMPLIANCE_RATIO} />
      </PreviewCard>
    </PreviewFrame>
  );
}

const DemoSlot = memo(function DemoSlot({ label, time, state }: { label: string; time: string; state: DemoSlotState }) {
  const active = state === 'active';
  const scale = useSharedValue(1);
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    if (!active || reduceMotion) return;
    scale.value = withRepeat(withTiming(ACTIVE_SLOT_PULSE_SCALE, { duration: ACTIVE_SLOT_PULSE_MS }), -1, true);
    return () => cancelAnimation(scale);
  }, [active, reduceMotion, scale]);

  const pulse = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));
  const text = active ? 'text-white' : 'text-ink-muted';
  const icon = state === 'taken' ? 'checkmark-circle-outline' : active ? 'medical' : 'ellipse-outline';
  const iconColor = active
    ? tokens.colors.surface.DEFAULT
    : state === 'taken'
      ? tokens.colors.ontime.solid
      : tokens.colors.line.strong;

  return (
    // className stays on a plain View: NativeWind styles core components, the Animated wrapper only scales.
    <View style={styles.slot}>
      <Animated.View style={[styles.slotFace, pulse]}>
        <View className={`flex-1 items-center justify-center rounded-full ${active ? 'bg-primary' : 'bg-canvas'}`}>
          {active && <View className="absolute right-0 top-0 h-2.5 w-2.5 rounded-full bg-missed-solid" />}
          <Text className={`text-caption ${text}`}>{label}</Text>
          <Icon name={icon} size={16} color={iconColor} />
          <Text className={`text-caption font-semibold ${text}`}>{time}</Text>
        </View>
      </Animated.View>
    </View>
  );
});

const styles = StyleSheet.create({
  // Keep the slot's size in native layout styles; NativeWind's aspect-square can measure to zero
  // when nested in the animated preview on device.
  slot: {
    width: '23%',
    aspectRatio: 1,
    marginBottom: tokens.spacing.sm,
  },
  slotFace: {
    flex: 1,
  },
});
