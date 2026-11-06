import { memo, useEffect, useState } from 'react';
import { Pressable, ScrollView, Text, View, type LayoutChangeEvent } from 'react-native';
import Animated, { ReduceMotion, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';

import { ONBOARDING_CONTENT, type OnboardingContent } from '@/components/onboarding/slides';
import { StatusPill } from '@/components/pillbox/ui';
import { PageDots } from '@/components/ui/page-dots';
import { AUTH_ASIDE_ROTATE_MS, AUTH_ASIDE_SLIDE_MS } from '@/constants/onboarding';
import { useAutoAdvance } from '@/hooks/use-auto-advance';

const COUNT = ONBOARDING_CONTENT.length;

/**
 * Brand panel beside the auth form on wide screens. Slides through the onboarding pages every
 * AUTH_ASIDE_ROTATE_MS; pauses while the pointer is over it, and the dots jump to a page.
 * All pages sit side by side in one track, so the panel is always as tall as the tallest page and
 * nothing around it jumps when the page changes. The slide follows the system "reduce motion" setting.
 */
export default function AuthAside() {
  const [hovered, setHovered] = useState(false);
  const [index, setIndex] = useAutoAdvance(COUNT, AUTH_ASIDE_ROTATE_MS, hovered);
  const [width, setWidth] = useState(0);
  const offset = useSharedValue(0);

  useEffect(() => {
    offset.value = withTiming(-index * width, { duration: AUTH_ASIDE_SLIDE_MS, reduceMotion: ReduceMotion.System });
  }, [index, width, offset]);

  const track = useAnimatedStyle(() => ({ transform: [{ translateX: offset.value }] }));
  const onLayout = (e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width);

  return (
    // Scrolls when the window is shorter than the panel; centered otherwise.
    <ScrollView
      className="flex-1 bg-primary-light"
      contentContainerClassName="flex-grow items-center justify-center p-12 xl:px-12 xl:py-8 2xl:px-16">
      <Pressable
        onHoverIn={() => setHovered(true)}
        onHoverOut={() => setHovered(false)}
        accessible={false}
        className="w-full max-w-[480px] gap-6 xl:max-w-[540px] 2xl:max-w-[600px]">
        <View className="overflow-hidden" onLayout={onLayout}>
          {width > 0 && (
            <Animated.View style={[{ width: width * COUNT }, track]}>
              <View className="flex-row">
                {ONBOARDING_CONTENT.map((content, i) => (
                  <AsidePage key={content.key} content={content} width={width} active={i === index} />
                ))}
              </View>
            </Animated.View>
          )}
        </View>
        <PageDots count={COUNT} index={index} onSelect={setIndex} />
      </Pressable>
    </ScrollView>
  );
}

const AsidePage = memo(function AsidePage({ content, width, active }: {
  content: OnboardingContent;
  width: number;
  active: boolean;
}) {
  const { Preview, badge, badgeIcon, title, body } = content;
  return (
    // Off-screen pages are hidden from screen readers and keyboard focus.
    <View
      style={{ width }}
      className="gap-6"
      accessibilityElementsHidden={!active}
      importantForAccessibility={active ? 'auto' : 'no-hide-descendants'}
      aria-hidden={!active}>
      <Preview />
      <View className="gap-3">
        <StatusPill label={badge} tone="primary" icon={badgeIcon} />
        <Text className="text-display font-bold tracking-tight text-ink xl:text-hero" accessibilityRole="header">
          {title}
        </Text>
        <Text className="text-body-sm text-ink-muted xl:text-body">{body}</Text>
      </View>
    </View>
  );
});
