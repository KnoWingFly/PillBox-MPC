import { Pressable, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';

import { Icon, type IconName, type Tone } from './ui';

/** `schedule` has no tab of its own: it opens from Beranda and PillBox and highlights PillBox. */
export type TabKey = 'home' | 'schedule' | 'notifications' | 'device' | 'settings';

type BarTab = Exclude<TabKey, 'schedule'>;

const TABS: { key: BarTab; label: string; icon: IconName; activeIcon: IconName }[] = [
  { key: 'home', label: Strings.tabs.home, icon: 'home-outline', activeIcon: 'home' },
  { key: 'device', label: Strings.tabs.device, icon: 'cube-outline', activeIcon: 'cube' },
  { key: 'notifications', label: Strings.tabs.notifications, icon: 'notifications-outline', activeIcon: 'notifications' },
  { key: 'settings', label: Strings.tabs.settings, icon: 'settings-outline', activeIcon: 'settings' },
];

const DOT: Partial<Record<Tone, string>> = {
  late: 'bg-late-solid',
  missed: 'bg-missed-solid',
};

export type TabBadges = {
  /** Unread notifications. */
  notifications: number;
  /** Unsaved schedule edits. */
  scheduleDirty: boolean;
  /** Shown as a dot when the pillbox needs attention. */
  deviceTone: Tone | null;
};

/** Bottom navigation between the dashboard sections (one screen; sections are swapped in place). */
export function TabBar({ active, onChange, badges }: { active: TabKey; onChange: (tab: TabKey) => void; badges: TabBadges }) {
  const insets = useSafeAreaInsets();

  return (
    <View
      accessibilityRole="tablist"
      className="flex-row border-t border-line bg-surface px-2 pt-2"
      style={{ paddingBottom: Math.max(insets.bottom, 8) }}>
      {TABS.map((tab) => {
        const selected = tab.key === active || (tab.key === 'device' && active === 'schedule');
        const count = tab.key === 'notifications' ? badges.notifications : 0;
        const dot =
          tab.key === 'device' && badges.scheduleDirty
            ? DOT.late
            : tab.key === 'device' && badges.deviceTone
              ? DOT[badges.deviceTone]
              : undefined;
        const extra =
          count > 0
            ? Strings.tabs.unread(count)
            : tab.key === 'device' && badges.scheduleDirty
              ? Strings.tabs.scheduleDirty
              : tab.key === 'device' && dot
                ? Strings.tabs.attention
                : '';
        return (
          <Pressable
            key={tab.key}
            accessibilityRole="tab"
            accessibilityLabel={`${tab.label}${extra}`}
            accessibilityState={{ selected }}
            onPress={() => onChange(tab.key)}
            className="min-h-[56px] flex-1 items-center gap-1 active:opacity-75">
            <View className={`h-8 w-16 items-center justify-center rounded-full ${selected ? 'bg-primary-light' : ''}`}>
              <Icon
                name={selected ? tab.activeIcon : tab.icon}
                size={22}
                color={selected ? tokens.colors.primary.dark : tokens.colors.ink.muted}
              />
              {count > 0 && (
                <View className="absolute -top-1 right-2 min-w-[20px] items-center rounded-full border-2 border-surface bg-missed-solid px-1">
                  <Text className="text-[11px] font-bold leading-4 text-white">{count > 99 ? '99+' : count}</Text>
                </View>
              )}
              {dot && <View className={`absolute right-3 top-0 h-2.5 w-2.5 rounded-full border-2 border-surface ${dot}`} />}
            </View>
            <Text className={`text-[13px] font-semibold ${selected ? 'text-primary-dark' : 'text-ink-muted'}`}>{tab.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}
