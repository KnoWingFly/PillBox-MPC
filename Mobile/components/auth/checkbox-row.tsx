import type { ReactNode } from 'react';
import { Pressable, View } from 'react-native';

import { Icon } from '@/components/pillbox/ui';
import * as tokens from '@/theme/tokens';

/** Checkbox with a label (plain or rich text) that toggles on a tap anywhere in the row. */
export default function CheckboxRow({ checked, onToggle, label, accessibilityLabel, accessibilityHint, disabled = false }: {
  checked: boolean;
  onToggle: () => void;
  label: ReactNode;
  accessibilityLabel: string;
  accessibilityHint?: string;
  disabled?: boolean;
}) {
  return (
    <Pressable
      onPress={onToggle}
      disabled={disabled}
      accessibilityRole="checkbox"
      accessibilityLabel={accessibilityLabel}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ checked, disabled }}
      className="min-h-[44px] shrink flex-row items-center gap-3 active:opacity-75">
      <Icon
        name={checked ? 'checkbox' : 'square-outline'}
        size={24}
        color={checked ? tokens.colors.primary.DEFAULT : tokens.colors.line.strong}
      />
      <View className="shrink">{label}</View>
    </Pressable>
  );
}
