import { memo } from 'react';
import { Pressable, View } from 'react-native';

import { Strings } from '@/constants/strings';

/** Extra touch area around each small dot so it reaches the 44 pt minimum. */
const DOT_HIT_SLOP = 12;

/**
 * Pager position: the current page is a wide bar, the others small dots. With `onSelect` each dot
 * jumps to its page, which is how a mouse user changes pages on web (there is no swipe).
 */
export function PageDots({ count, index, onSelect }: { count: number; index: number; onSelect?: (index: number) => void }) {
  return (
    <View className="flex-row items-center justify-center gap-2" accessibilityRole="tablist">
      {Array.from({ length: count }, (_, i) => (
        <Dot key={i} page={i} count={count} active={i === index} onSelect={onSelect} />
      ))}
    </View>
  );
}

const Dot = memo(function Dot({ page, count, active, onSelect }: {
  page: number;
  count: number;
  active: boolean;
  onSelect?: (index: number) => void;
}) {
  return (
    <Pressable
      accessibilityRole="tab"
      accessibilityLabel={Strings.onboarding.pageA11y(page + 1, count)}
      accessibilityState={{ selected: active }}
      disabled={!onSelect}
      onPress={() => onSelect?.(page)}
      hitSlop={DOT_HIT_SLOP}
      className="py-2">
      <View className={`h-2 rounded-full ${active ? 'w-10 bg-primary' : 'w-2 bg-line'}`} />
    </Pressable>
  );
});
