import { useRef, type ReactNode } from 'react';
import { Pressable, Text } from 'react-native';
import ReanimatedSwipeable, { type SwipeableMethods } from 'react-native-gesture-handler/ReanimatedSwipeable';

import { Icon } from './ui';

/**
 * Swipe left to reveal a "Hapus" action. Screen-reader users get the same action through the
 * child's `accessibilityActions` (see NotificationItem), because a swipe is not discoverable.
 */
export function SwipeToDelete({
  children,
  onDelete,
  label = 'Hapus',
}: {
  children: ReactNode;
  onDelete: () => void;
  label?: string;
}) {
  const ref = useRef<SwipeableMethods>(null);

  return (
    <ReanimatedSwipeable
      ref={ref}
      friction={2}
      rightThreshold={48}
      overshootRight={false}
      renderRightActions={() => (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={label}
          onPress={() => {
            ref.current?.close();
            onDelete();
          }}
          className="ml-2 w-24 items-center justify-center gap-1 rounded-3xl bg-missed-solid active:opacity-80">
          <Icon name="trash-outline" size={22} color="#FFFFFF" />
          <Text className="text-body-sm font-semibold text-white">{label}</Text>
        </Pressable>
      )}>
      {children}
    </ReanimatedSwipeable>
  );
}
