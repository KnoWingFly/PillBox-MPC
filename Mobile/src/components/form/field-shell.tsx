import type { ReactNode } from 'react';
import { Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';

import { Icon } from '../pillbox/ui';

export function FieldError({ text }: { text: string }) {
  return (
    <View className="flex-row items-start gap-2" accessibilityRole="alert" accessibilityLiveRegion="polite">
      <Icon name="alert-circle" size={18} color={tokens.colors.missed.fg} />
      <Text className="flex-1 text-body-sm font-semibold text-missed-fg">{text}</Text>
    </View>
  );
}

/** Label (with an optional required marker), the control, then a helper line or an error. */
export function FieldShell({
  label,
  required = false,
  hint,
  error,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string | null;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <View className="gap-1.5">
      <Text className="text-body-sm font-semibold text-ink">
        {label}
        {required && (
          <Text className="text-missed-fg" accessibilityLabel={Strings.elderlyForm.requiredA11y}>
            {` ${Strings.elderlyForm.requiredMarker}`}
          </Text>
        )}
      </Text>
      {children}
      {error ? <FieldError text={error} /> : hint ? <Text className="text-caption text-ink-muted">{hint}</Text> : null}
    </View>
  );
}

/** Border classes shared by every input box. */
export function inputBorder(error?: string | null): string {
  return error ? 'border-missed-solid' : 'border-line-strong';
}
