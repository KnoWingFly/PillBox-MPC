// Building blocks of the redesigned dashboard tabs (Beranda, PillBox, Notifikasi, Pengaturan).
// The primitives they sit on (Icon, IconBadge, Button, Card, StatusPill) live in ./ui.tsx.

import type { ReactNode } from 'react';
import { Pressable, Switch, Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';

import { BrandHeader } from '../ui/brand-header';
import { Icon, IconBadge, TONE, type IconName, type Tone } from './ui';

/** Fill colors per tone for drawn shapes (ring, bar) that cannot take classes. */
const TONE_FILL: Record<Tone, string> = {
  primary: tokens.colors.primary.DEFAULT,
  ontime: tokens.colors.ontime.solid,
  late: tokens.colors.late.solid,
  missed: tokens.colors.missed.solid,
  info: tokens.colors.info.solid,
  battery: tokens.colors.battery.fg,
  neutral: tokens.colors.ink.muted,
};

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return parts.slice(0, 2).map((p) => p[0]!.toUpperCase()).join('');
}

/** Round initials avatar, with an optional presence dot. */
export function Avatar({ name, size = 'md', online }: { name: string; size?: 'md' | 'lg'; online?: boolean }) {
  const box = size === 'lg' ? 'h-16 w-16' : 'h-11 w-11';
  return (
    <View accessible accessibilityRole="image" accessibilityLabel={Strings.shell.avatarA11y(name)}>
      <View className={`items-center justify-center rounded-full bg-primary-light ${box}`}>
        <Text className={`font-bold text-primary-dark ${size === 'lg' ? 'text-title' : 'text-body-sm'}`}>{initials(name)}</Text>
      </View>
      {online !== undefined && (
        <View
          className={`absolute bottom-0 right-0 h-3.5 w-3.5 rounded-full border-2 border-surface ${
            online ? 'bg-ontime-solid' : 'bg-ink-subtle'
          }`}
        />
      )}
    </View>
  );
}

/** Brand bar at the top of every dashboard tab. */
export function TopBar({ userName }: { userName: string }) {
  return (
    <View className="border-b border-line bg-surface px-4">
      <BrandHeader right={<Avatar name={userName} online />} />
    </View>
  );
}

/** Heading of a group of cards (Pengaturan), with an optional note on the right. */
export function SectionTitle({ icon, title, right }: { icon: IconName; title: string; right?: ReactNode }) {
  return (
    <View className="mt-2 flex-row items-center gap-2">
      <Icon name={icon} size={20} color={tokens.colors.primary.DEFAULT} />
      <Text className="flex-1 text-body font-bold text-ink" accessibilityRole="header">
        {title}
      </Text>
      {right}
    </View>
  );
}

/** Small count pill next to a title or a filter ("Pusat Notifikasi 3"). */
export function CountBadge({ count, tone = 'missed' }: { count: number; tone?: Tone }) {
  if (count <= 0) return null;
  return (
    <View className={`min-w-[24px] items-center rounded-full px-1.5 ${TONE[tone].solid}`}>
      <Text className="text-caption font-bold text-white">{count > 99 ? '99+' : count}</Text>
    </View>
  );
}

const RING_SIZE = 112;
const RING_STROKE = 10;
const HALF = RING_SIZE / 2;
/** Room for the ring's label: the hole, minus a small gap from the stroke. */
const RING_LABEL_WIDTH = RING_SIZE - 2 * RING_STROKE - 2 * RING_STROKE / 2;
const FULL_TURN = 360;
const HALF_TURN = 180;
/** A circle with its top and left borders colored draws a half ring tilted by 45 degrees. */
const RING_TILT = 45;

function HalfArc({ color, degrees }: { color: string; degrees: number }) {
  return (
    <View
      style={{
        position: 'absolute',
        width: RING_SIZE,
        height: RING_SIZE,
        borderRadius: HALF,
        borderWidth: RING_STROKE,
        borderTopColor: color,
        borderLeftColor: color,
        borderRightColor: 'transparent',
        borderBottomColor: 'transparent',
        transform: [{ rotate: `${degrees - RING_TILT}deg` }],
      }}
    />
  );
}

/** Circular progress (0-100) drawn with views (no SVG dependency); `children` sit in the middle. */
export function ProgressRing({ percent, tone, children }: { percent: number | null; tone: Tone; children: ReactNode }) {
  const arc = (Math.max(0, Math.min(100, percent ?? 0)) / 100) * FULL_TURN;
  const color = TONE_FILL[tone];
  return (
    <View style={{ width: RING_SIZE, height: RING_SIZE }} className="items-center justify-center">
      <View
        className="absolute inset-0 rounded-full border-line"
        style={{ borderWidth: RING_STROKE }}
      />
      {arc > 0 && (
        <View style={{ position: 'absolute', left: HALF, top: 0, width: HALF, height: RING_SIZE, overflow: 'hidden' }}>
          <View style={{ position: 'absolute', left: -HALF }}>
            <HalfArc color={color} degrees={Math.min(arc, HALF_TURN)} />
          </View>
        </View>
      )}
      {arc > HALF_TURN && (
        <View style={{ position: 'absolute', left: 0, top: 0, width: HALF, height: RING_SIZE, overflow: 'hidden' }}>
          <HalfArc color={color} degrees={arc} />
        </View>
      )}
      <View className="items-center" style={{ width: RING_LABEL_WIDTH }}>
        {children}
      </View>
    </View>
  );
}

/** Horizontal progress bar (0-100). */
export function ProgressBar({ percent, tone }: { percent: number; tone: Tone }) {
  const value = Math.max(0, Math.min(100, percent));
  return (
    <View className="h-2.5 flex-row overflow-hidden rounded-full bg-canvas">
      <View className={`rounded-full ${TONE[tone].solid}`} style={{ flex: value }} />
      <View style={{ flex: 100 - value }} />
    </View>
  );
}

/** Icon + label + value tile on a soft background (Jaringan, Baterai, Rata-rata tunda). */
export function StatTile({ icon, label, value, tone = 'neutral' }: { icon: IconName; label: string; value: string; tone?: Tone }) {
  return (
    <View
      className={`flex-1 flex-row items-center gap-3 rounded-2xl p-3 ${TONE[tone].soft}`}
      accessible
      accessibilityLabel={`${label}: ${value}`}>
      <IconBadge icon={icon} tone={tone} size="sm" />
      <View className="flex-1">
        <Text className="text-caption text-ink-muted">{label}</Text>
        <Text className={`text-body font-bold ${tone === 'neutral' ? 'text-ink' : TONE[tone].fg}`} numberOfLines={1}>
          {value}
        </Text>
      </View>
    </View>
  );
}

/** Tappable row with an icon, title and subtitle (settings lists, "Hubungkan Pillbox"). */
export function ListRow({
  icon,
  tone = 'primary',
  title,
  subtitle,
  subtitleClassName = 'text-ink-muted',
  right,
  onPress,
}: {
  icon: IconName;
  tone?: Tone;
  title: string;
  subtitle?: string;
  subtitleClassName?: string;
  /** Replaces the chevron. */
  right?: ReactNode;
  onPress?: () => void;
}) {
  const body = (
    <>
      <IconBadge icon={icon} tone={tone} size="sm" />
      <View className="flex-1">
        <Text className="text-body font-semibold text-ink">{title}</Text>
        {subtitle && <Text className={`text-body-sm ${subtitleClassName}`}>{subtitle}</Text>}
      </View>
      {right ?? (onPress ? <Icon name="chevron-forward" size={20} color={tokens.colors.ink.muted} /> : null)}
    </>
  );
  const row = 'min-h-[56px] flex-row items-center gap-3 py-2';
  if (!onPress) {
    return (
      <View className={row} accessible accessibilityLabel={subtitle ? `${title}. ${subtitle}` : title}>
        {body}
      </View>
    );
  }
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={subtitle ? `${title}. ${subtitle}` : title}
      onPress={onPress}
      className={`${row} rounded-2xl active:opacity-75`}>
      {body}
    </Pressable>
  );
}

/** Title + description + switch. */
export function SwitchRow({
  title,
  text,
  value,
  onChange,
  disabled = false,
}: {
  title: string;
  text?: string;
  value: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <View className="min-h-[56px] flex-row items-center gap-3 py-2">
      <View className="flex-1">
        <Text className="text-body font-semibold text-ink">{title}</Text>
        {text && <Text className="text-body-sm text-ink-muted">{text}</Text>}
      </View>
      <Switch
        accessibilityLabel={title}
        accessibilityHint={text}
        value={value}
        disabled={disabled}
        onValueChange={onChange}
        trackColor={{ false: tokens.colors.line.strong, true: tokens.colors.primary.DEFAULT }}
        thumbColor={tokens.colors.surface.DEFAULT}
      />
    </View>
  );
}

/** Round shortcut button with a label underneath (Aksi Cepat). */
export function QuickAction({ icon, label, onPress, dot = false }: { icon: IconName; label: string; onPress: () => void; dot?: boolean }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      className="min-h-[44px] flex-1 items-center gap-2 py-1 active:opacity-75">
      <View>
        <IconBadge icon={icon} tone="primary" size="lg" />
        {dot && <View className="absolute right-0 top-0 h-3 w-3 rounded-full border-2 border-surface bg-missed-solid" />}
      </View>
      <Text className="text-body-sm font-semibold text-ink" numberOfLines={1}>
        {label}
      </Text>
    </Pressable>
  );
}

/** Compact text link with a chevron, for card headers ("Jadwal Lengkap"). */
export function TextLink({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="link"
      accessibilityLabel={label}
      onPress={onPress}
      hitSlop={8}
      className="min-h-[44px] flex-row items-center gap-0.5 active:opacity-75">
      <Text className="text-body-sm font-bold text-primary">{label}</Text>
      <Icon name="chevron-forward" size={16} color={tokens.colors.primary.DEFAULT} />
    </Pressable>
  );
}
