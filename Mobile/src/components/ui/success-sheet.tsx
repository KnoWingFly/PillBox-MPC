import type { ReactNode } from 'react';
import { Modal, Pressable, ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';

import { Button, Icon, type IconName } from '../pillbox/ui';

export type SheetAction = { label: string; icon?: IconName; onPress: () => void };

/** done = green check; pending = amber hourglass (sent, but not confirmed yet). */
export type SheetTone = 'done' | 'pending';

const BADGE: Record<SheetTone, { ring: string; fill: string; icon: IconName }> = {
  done: { ring: 'bg-ontime-soft', fill: 'bg-ontime-solid', icon: 'checkmark' },
  pending: { ring: 'bg-late-soft', fill: 'bg-late-solid', icon: 'hourglass-outline' },
};
const BADGE_ICON_SIZE = 36;

/**
 * Bottom sheet confirming a finished action ("Profil Lansia Berhasil Disimpan!", "Jadwal Obat
 * Berhasil Disinkronkan!"): check badge, title, message, a summary card and up to three actions.
 * Tapping the backdrop or Android back runs `onClose`.
 */
export function SuccessSheet({
  visible,
  tone = 'done',
  title,
  message,
  primary,
  secondary,
  link,
  onClose,
  children,
}: {
  visible: boolean;
  tone?: SheetTone;
  title: string;
  message: string;
  primary: SheetAction;
  secondary?: SheetAction;
  /** Plain text action under the buttons. */
  link?: SheetAction;
  onClose: () => void;
  /** Summary card content. */
  children?: ReactNode;
}) {
  const insets = useSafeAreaInsets();
  const badge = BADGE[tone];
  return (
    // statusBarTranslucent: on Android the backdrop also covers the status bar instead of stopping under it.
    <Modal visible={visible} transparent animationType="slide" statusBarTranslucent onRequestClose={onClose}>
      <View className="flex-1 justify-end">
        <Pressable
          className="absolute inset-0 bg-black/40"
          onPress={onClose}
          accessibilityRole="button"
          accessibilityLabel={Strings.common.close}
        />
        <View
          className="max-h-[92%] w-full max-w-[480px] self-center rounded-t-3xl bg-surface"
          style={{ boxShadow: tokens.shadow.raised }}
          accessibilityViewIsModal>
          <ScrollView
            contentContainerClassName="items-center gap-4 px-5 pt-3"
            contentContainerStyle={{ paddingBottom: insets.bottom + tokens.spacing.xl }}>
            <View className="h-1.5 w-12 rounded-full bg-line" />
            <View className={`h-24 w-24 items-center justify-center rounded-full ${badge.ring}`}>
              <View className={`h-16 w-16 items-center justify-center rounded-full ${badge.fill}`}>
                <Icon name={badge.icon} size={BADGE_ICON_SIZE} color={tokens.colors.surface.DEFAULT} />
              </View>
            </View>
            <View className="items-center gap-1">
              <Text className="text-center text-heading font-bold text-ink" accessibilityRole="header">
                {title}
              </Text>
              <Text className="text-center text-body-sm text-ink-muted">{message}</Text>
            </View>
            {children && <View className="w-full gap-3 rounded-3xl bg-canvas p-4">{children}</View>}
            <View className="w-full gap-2">
              <Button label={primary.label} icon={primary.icon} onPress={primary.onPress} />
              {secondary && <Button label={secondary.label} icon={secondary.icon} variant="secondary" onPress={secondary.onPress} />}
              {link && <Button label={link.label} icon={link.icon} variant="ghost" size="sm" onPress={link.onPress} />}
            </View>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}
