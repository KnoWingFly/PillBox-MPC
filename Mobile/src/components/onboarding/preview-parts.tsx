// Small building blocks shared by the three onboarding illustrations.
import type { ReactNode } from 'react';
import { Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';

import { Icon, type IconName } from '../pillbox/ui';

/** Rounded tinted frame around an illustration; read by screen readers as one image. */
export function PreviewFrame({ children }: { children: ReactNode }) {
  return (
    <View
      className="gap-3 rounded-3xl bg-primary-light p-4"
      accessible
      accessibilityRole="image"
      accessibilityLabel={Strings.onboarding.previewA11y}>
      {children}
    </View>
  );
}

/** White card inside a preview. */
export function PreviewCard({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <View className={`gap-3 rounded-2xl bg-surface p-3 ${className}`} style={{ boxShadow: tokens.shadow.card }}>
      {children}
    </View>
  );
}

/** White rounded label with an optional icon or dot. */
export function PreviewPill({ label, icon, iconColor = tokens.colors.primary.DEFAULT, dot = false }: {
  label: string;
  icon?: IconName;
  iconColor?: string;
  dot?: boolean;
}) {
  return (
    <View className="flex-row items-center gap-1.5 self-start rounded-full bg-surface px-3 py-1.5">
      {dot && <View className="h-2 w-2 rounded-full bg-ontime-solid" />}
      {icon && <Icon name={icon} size={16} color={iconColor} />}
      <Text className="text-caption font-semibold text-ink">{label}</Text>
    </View>
  );
}

/** Thin horizontal progress bar; `ratio` is 0..1. */
export function ProgressBar({ ratio }: { ratio: number }) {
  return (
    <View className="h-2 overflow-hidden rounded-full bg-primary-light">
      <View className="h-full rounded-full bg-primary" style={{ width: `${Math.round(ratio * 100)}%` }} />
    </View>
  );
}
