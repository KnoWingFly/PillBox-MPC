// Shared building blocks for the pillbox dashboard. All colors and sizes come from src/theme/tokens.js
// through Tailwind classes; class strings are written out in full so Tailwind can find them.

import Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps, ReactNode } from 'react';
import { ActivityIndicator, Pressable, Text, View } from 'react-native';

import * as tokens from '@/theme/tokens';

export type IconName = ComponentProps<typeof Ionicons>['name'];
export type Tone = 'primary' | 'ontime' | 'late' | 'missed' | 'info' | 'battery' | 'neutral';

/** Soft background + readable foreground per tone (all pairs pass WCAG AA, see tokens.js). */
export const TONE: Record<Tone, { soft: string; fg: string; solid: string; icon: string }> = {
  primary: { soft: 'bg-primary-light', fg: 'text-primary-dark', solid: 'bg-primary', icon: tokens.colors.primary.dark },
  ontime: { soft: 'bg-ontime-soft', fg: 'text-ontime-fg', solid: 'bg-ontime-solid', icon: tokens.colors.ontime.fg },
  late: { soft: 'bg-late-soft', fg: 'text-late-fg', solid: 'bg-late-solid', icon: tokens.colors.late.fg },
  missed: { soft: 'bg-missed-soft', fg: 'text-missed-fg', solid: 'bg-missed-solid', icon: tokens.colors.missed.fg },
  info: { soft: 'bg-info-soft', fg: 'text-info-fg', solid: 'bg-info-solid', icon: tokens.colors.info.fg },
  battery: { soft: 'bg-battery-soft', fg: 'text-battery-fg', solid: 'bg-battery-fg', icon: tokens.colors.battery.fg },
  neutral: { soft: 'bg-canvas', fg: 'text-ink-muted', solid: 'bg-ink-muted', icon: tokens.colors.ink.muted },
};

export function Icon({ name, size = 22, color = tokens.colors.ink.DEFAULT }: { name: IconName; size?: number; color?: string }) {
  return <Ionicons name={name} size={size} color={color} accessibilityElementsHidden importantForAccessibility="no" />;
}

/** Round icon on a soft tone background. */
export function IconBadge({ icon, tone, size = 'md' }: { icon: IconName; tone: Tone; size?: 'sm' | 'md' | 'lg' }) {
  const box = size === 'lg' ? 'h-14 w-14' : size === 'sm' ? 'h-9 w-9' : 'h-11 w-11';
  return (
    <View className={`items-center justify-center rounded-full ${box} ${TONE[tone].soft}`}>
      <Icon name={icon} size={size === 'lg' ? 28 : size === 'sm' ? 18 : 22} color={TONE[tone].icon} />
    </View>
  );
}

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'danger-soft' | 'success' | 'warning' | 'ghost';

const BUTTON: Record<ButtonVariant, { box: string; text: string; color: string }> = {
  primary: { box: 'bg-primary', text: 'text-white', color: '#FFFFFF' },
  secondary: { box: 'bg-primary-light', text: 'text-primary-dark', color: tokens.colors.primary.dark },
  danger: { box: 'bg-missed-solid', text: 'text-white', color: '#FFFFFF' },
  'danger-soft': { box: 'bg-missed-soft', text: 'text-missed-fg', color: tokens.colors.missed.fg },
  success: { box: 'bg-ontime-solid', text: 'text-white', color: '#FFFFFF' },
  warning: { box: 'bg-late-solid', text: 'text-white', color: '#FFFFFF' },
  ghost: { box: 'bg-transparent', text: 'text-primary', color: tokens.colors.primary.DEFAULT },
};

export function Button({
  label,
  icon,
  onPress,
  variant = 'primary',
  size = 'md',
  disabled = false,
  loading = false,
  accessibilityLabel,
}: {
  label: string;
  icon?: IconName;
  onPress: () => void;
  variant?: ButtonVariant;
  size?: 'sm' | 'md';
  disabled?: boolean;
  loading?: boolean;
  /** Spoken label when `label` alone is not clear (e.g. "+5"). */
  accessibilityLabel?: string;
}) {
  const style = BUTTON[variant];
  const inactive = disabled || loading;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled: inactive, busy: loading }}
      disabled={inactive}
      onPress={onPress}
      className={`flex-row items-center justify-center gap-2 rounded-2xl active:opacity-75 ${
        size === 'sm' ? 'min-h-[44px] px-4' : 'min-h-[52px] px-5'
      } ${style.box} ${inactive ? 'opacity-50' : ''}`}>
      {loading ? (
        <ActivityIndicator color={style.color} />
      ) : (
        <>
          {icon && <Icon name={icon} size={size === 'sm' ? 18 : 20} color={style.color} />}
          <Text className={`text-center font-semibold ${size === 'sm' ? 'text-body-sm' : 'text-body'} ${style.text}`}>
            {label}
          </Text>
        </>
      )}
    </Pressable>
  );
}

export function Chip({
  label,
  selected,
  onPress,
  disabled = false,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
  disabled?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ selected, disabled }}
      disabled={disabled}
      onPress={onPress}
      className={`min-h-[44px] min-w-[44px] items-center justify-center rounded-full border px-4 active:opacity-75 ${
        selected ? 'border-primary bg-primary' : 'border-line bg-surface'
      } ${disabled ? 'opacity-40' : ''}`}>
      <Text className={`text-body-sm font-semibold ${selected ? 'text-white' : 'text-ink'}`}>{label}</Text>
    </Pressable>
  );
}

export function Card({
  title,
  subtitle,
  icon,
  tone = 'primary',
  right,
  children,
}: {
  title?: string;
  subtitle?: string;
  icon?: IconName;
  tone?: Tone;
  right?: ReactNode;
  children: ReactNode;
}) {
  return (
    <View className="gap-4 rounded-3xl border border-line bg-surface p-5" style={{ boxShadow: tokens.shadow.card }}>
      {title && (
        <View className="flex-row items-center gap-3">
          {icon && <IconBadge icon={icon} tone={tone} size="sm" />}
          <View className="flex-1">
            <Text className="text-title font-bold text-ink" accessibilityRole="header">
              {title}
            </Text>
            {subtitle && <Text className="text-body-sm text-ink-muted">{subtitle}</Text>}
          </View>
          {right}
        </View>
      )}
      {children}
    </View>
  );
}

/** Large page title at the top of each tab. */
export function ScreenHeader({ eyebrow, title, subtitle, right }: { eyebrow?: string; title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <View className="flex-row items-end justify-between gap-3 pb-1">
      <View className="flex-1 gap-0.5">
        {eyebrow && <Text className="text-body-sm font-semibold text-primary">{eyebrow}</Text>}
        <Text className="text-display font-bold tracking-tight text-ink" accessibilityRole="header">
          {title}
        </Text>
        {subtitle && <Text className="text-body-sm text-ink-muted">{subtitle}</Text>}
      </View>
      {right}
    </View>
  );
}

export function StatusPill({ label, tone, icon }: { label: string; tone: Tone; icon?: IconName }) {
  return (
    <View className={`flex-row items-center gap-1.5 rounded-full px-3 py-1.5 ${TONE[tone].soft}`}>
      {icon ? <Icon name={icon} size={16} color={TONE[tone].icon} /> : <View className={`h-2 w-2 rounded-full ${TONE[tone].solid}`} />}
      <Text className={`text-body-sm font-semibold ${TONE[tone].fg}`}>{label}</Text>
    </View>
  );
}

export function InfoRow({
  icon,
  label,
  value,
  valueClassName = 'text-ink',
}: {
  icon?: IconName;
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <View className="min-h-[44px] flex-row items-center gap-3" accessible accessibilityLabel={`${label}: ${value}`}>
      {icon && <Icon name={icon} size={20} color={tokens.colors.ink.muted} />}
      <Text className="text-body text-ink-muted">{label}</Text>
      <Text className={`flex-1 text-right text-body font-semibold ${valueClassName}`}>{value}</Text>
    </View>
  );
}

export function Divider() {
  return <View className="h-px bg-line" />;
}

export function LoadErrorBox({ text, onRetry }: { text: string; onRetry: () => void }) {
  return (
    <View className="gap-3 rounded-2xl bg-missed-soft p-4" accessibilityRole="alert">
      <View className="flex-row items-start gap-2">
        <Icon name="cloud-offline-outline" size={22} color={tokens.colors.missed.fg} />
        <Text className="flex-1 text-body text-missed-fg">{text}</Text>
      </View>
      <Button label="Coba lagi" icon="refresh" variant="danger-soft" size="sm" onPress={onRetry} />
    </View>
  );
}

export function EmptyState({ icon, title, text }: { icon: IconName; title: string; text: string }) {
  return (
    <View className="items-center gap-2 px-6 py-10">
      <IconBadge icon={icon} tone="neutral" size="lg" />
      <Text className="mt-1 text-center text-title font-semibold text-ink">{title}</Text>
      <Text className="text-center text-body-sm text-ink-muted">{text}</Text>
    </View>
  );
}
