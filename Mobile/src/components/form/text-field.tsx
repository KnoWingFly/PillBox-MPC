import type { ComponentProps } from 'react';
import { TextInput } from 'react-native';

import * as tokens from '@/theme/tokens';

import { FieldShell, inputBorder } from './field-shell';

/** Labelled, token-styled text input with a required marker and an inline error. */
export function TextField({
  label,
  required,
  hint,
  error,
  ...props
}: {
  label: string;
  required?: boolean;
  hint?: string | null;
  error?: string | null;
} & ComponentProps<typeof TextInput>) {
  return (
    <FieldShell label={label} required={required} hint={hint} error={error}>
      <TextInput
        className={`min-h-[52px] rounded-2xl border bg-surface px-4 text-body text-ink ${inputBorder(error)}`}
        placeholderTextColor={tokens.colors.ink.subtle}
        autoCorrect={false}
        accessibilityLabel={label}
        {...props}
      />
    </FieldShell>
  );
}
