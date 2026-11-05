import { Text, View } from 'react-native';

import * as tokens from '@/theme/tokens';

import { Icon } from '../pillbox/ui';

/** Lock icon and a short line about data protection, shown at the bottom of the entry screens. */
export function SecurityNote({ text, boxed = false }: { text: string; boxed?: boolean }) {
  return (
    <View
      className={`flex-row items-center justify-center gap-2 self-center ${boxed ? 'rounded-full bg-surface-muted px-4 py-2' : ''}`}>
      <Icon name="lock-closed-outline" size={16} color={tokens.colors.ontime.fg} />
      <Text className="shrink text-center text-caption text-ink-muted">{text}</Text>
    </View>
  );
}
