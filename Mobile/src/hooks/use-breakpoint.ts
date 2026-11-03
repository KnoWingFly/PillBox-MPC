import { useWindowDimensions } from 'react-native';

import * as tokens from '@/theme/tokens';

/**
 * True when the window is at least the given breakpoint wide (same values as Tailwind's `md:` / `lg:`).
 * Prefer the class prefixes for styling; use this only to avoid mounting content a layout hides.
 */
export function useMinWidth(name: keyof typeof tokens.breakpoints): boolean {
  const { width } = useWindowDimensions();
  return width >= tokens.breakpoints[name];
}
