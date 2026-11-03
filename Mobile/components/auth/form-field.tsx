import { useState, type ReactNode } from 'react';
import { Pressable, Text, TextInput, View, type TextInputProps } from 'react-native';

import { FieldShell, inputBorder } from '@/components/form/field-shell';
import { Icon, type IconName } from '@/components/pillbox/ui';
import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';

type Props = TextInputProps & {
  label: string;
  /** Leading icon inside the box. */
  icon?: IconName;
  /** Fixed text in front of the input, e.g. the "+62" country code. */
  prefix?: string;
  /** Shown at the right of the label (a hint or a badge). */
  labelRight?: ReactNode;
  hint?: string | null;
  error?: string | null;
  /** Password field with a show/hide button. */
  secureToggle?: boolean;
  /** Content under the input (e.g. a password strength meter). */
  footer?: ReactNode;
};

// Labeled auth input. Spacing below is built in (mb-4) so the auth screens can simply stack fields.
export default function FormField({ label, icon, prefix, labelRight, hint, error, secureToggle, footer, ...inputProps }: Props) {
  const [hidden, setHidden] = useState(true);

  return (
    <View className="mb-4 gap-2">
      <FieldShell label={label} labelRight={labelRight} hint={hint} error={error}>
        <View className={`min-h-[52px] flex-row items-center overflow-hidden rounded-2xl border bg-surface ${inputBorder(error)}`}>
          {prefix && (
            <View className="min-h-[52px] justify-center border-r border-line bg-canvas px-4">
              <Text className="text-body font-semibold text-ink">{prefix}</Text>
            </View>
          )}
          {icon && (
            <View className="pl-4">
              <Icon name={icon} size={20} color={tokens.colors.ink.muted} />
            </View>
          )}
          <TextInput
            className="min-h-[52px] flex-1 px-3 text-body text-ink"
            placeholderTextColor={tokens.colors.ink.subtle}
            secureTextEntry={secureToggle ? hidden : inputProps.secureTextEntry}
            autoCorrect={false}
            accessibilityLabel={label}
            {...inputProps}
          />
          {secureToggle && (
            <Pressable
              onPress={() => setHidden((h) => !h)}
              className="min-h-[44px] min-w-[44px] items-center justify-center px-3 active:opacity-75"
              accessibilityRole="button"
              accessibilityLabel={hidden ? Strings.auth.showPassword : Strings.auth.hidePassword}>
              <Icon name={hidden ? 'eye-outline' : 'eye-off-outline'} size={22} color={tokens.colors.ink.muted} />
            </Pressable>
          )}
        </View>
      </FieldShell>
      {footer}
    </View>
  );
}
