/**
 * Learn more about light and dark modes:
 * https://docs.expo.dev/guides/color-schemes/
 */

import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';

export function useTheme() {
  const scheme = useColorScheme();
  // React Native 0.88 reports an unknown scheme as null (it used to be 'unspecified').
  const theme = scheme ?? 'light';

  return Colors[theme];
}
