import { useEffect, useRef, useState, type ComponentRef, type ReactNode } from 'react';
import { ScrollView, View, type LayoutChangeEvent, type NativeScrollEvent, type NativeSyntheticEvent } from 'react-native';

/** Distance (px) from a page edge that still counts as "settled on that page". */
const SETTLE_TOLERANCE_PX = 1;

/**
 * Horizontal, swipeable pages. Controlled: `index` scrolls the pager, a swipe reports the new page.
 * Pages take the measured size (not the window), so it also works inside a max-width web layout.
 */
export function Pager({ pages, index, onIndexChange }: {
  pages: readonly ReactNode[];
  index: number;
  onIndexChange: (index: number) => void;
}) {
  const ref = useRef<ComponentRef<typeof ScrollView>>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const { width } = size;

  const offset = useRef(0);
  // Target of an animated scrollTo still in flight; swipe reports are ignored until it lands.
  const target = useRef<number | null>(null);

  useEffect(() => {
    if (!width) return;
    const x = index * width;
    if (Math.abs(offset.current - x) <= SETTLE_TOLERANCE_PX) return;
    target.current = x;
    ref.current?.scrollTo({ x, animated: true });
  }, [index, width]);

  const onLayout = (e: LayoutChangeEvent) => {
    const { width: w, height: h } = e.nativeEvent.layout;
    setSize({ width: w, height: h });
  };

  // onScroll (not onMomentumScrollEnd, which web lacks). Report only once the scroll rests on a page
  // edge, so a swipe is reported once and the pager does not fight its own scrollTo.
  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const x = e.nativeEvent.contentOffset.x;
    offset.current = x;
    if (!width) return;
    if (target.current !== null) {
      if (Math.abs(x - target.current) <= SETTLE_TOLERANCE_PX) target.current = null;
      return;
    }
    const page = Math.round(x / width);
    if (Math.abs(x - page * width) <= SETTLE_TOLERANCE_PX && page !== index) onIndexChange(page);
  };

  return (
    <View className="flex-1" onLayout={onLayout}>
      {width > 0 && (
        <ScrollView
          ref={ref}
          horizontal
          pagingEnabled
          showsHorizontalScrollIndicator={false}
          onScroll={onScroll}
          scrollEventThrottle={16}>
          {pages.map((page, i) => (
            <View key={i} style={size}>
              {page}
            </View>
          ))}
        </ScrollView>
      )}
    </View>
  );
}
