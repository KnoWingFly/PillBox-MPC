import { Pressable, Text, View } from 'react-native';

import { FieldShell, inputBorder } from './field-shell';

export type SegmentOption<T extends string> = { value: T; label: string };

/** Equal-width segmented control; one option or none selected. */
export function SegmentedChoice<T extends string>({
  label,
  required,
  options,
  value,
  onChange,
  error,
  disabled = false,
}: {
  label: string;
  required?: boolean;
  options: readonly SegmentOption<T>[];
  value: T | null;
  onChange: (value: T) => void;
  error?: string | null;
  disabled?: boolean;
}) {
  return (
    <FieldShell label={label} required={required} error={error}>
      <View
        accessibilityRole="radiogroup"
        accessibilityLabel={label}
        className={`flex-row gap-1 rounded-2xl border bg-canvas p-1 ${inputBorder(error)}`}>
        {options.map((option) => {
          const selected = option.value === value;
          return (
            <Pressable
              key={option.value}
              accessibilityRole="radio"
              accessibilityLabel={option.label}
              accessibilityState={{ selected, disabled }}
              disabled={disabled}
              onPress={() => onChange(option.value)}
              className={`min-h-[44px] flex-1 items-center justify-center rounded-xl active:opacity-75 ${
                selected ? 'bg-primary' : 'bg-transparent'
              }`}>
              <Text className={`text-body-sm font-semibold ${selected ? 'text-white' : 'text-ink'}`}>{option.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </FieldShell>
  );
}
