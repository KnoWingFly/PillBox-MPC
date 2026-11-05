import { Text, View } from 'react-native';

import { Icon } from '@/components/pillbox/ui';
import * as tokens from '@/theme/tokens';

/** Why the user is back on Masuk (e.g. the session expired). */
export default function SessionNotice({ text }: { text: string }) {
  return (
    <View accessibilityRole="alert" className="mb-4 flex-row items-start gap-2 rounded-2xl border border-late-border bg-late-soft px-4 py-3">
      <Icon name="time-outline" size={18} color={tokens.colors.late.fg} />
      <Text className="flex-1 text-body-sm text-late-fg">{text}</Text>
    </View>
  );
}
