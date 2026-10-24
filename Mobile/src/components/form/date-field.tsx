import { DateTimePicker } from '@expo/ui/community/datetime-picker';
import { useState } from 'react';
import { Platform, Pressable, TextInput, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';

import { Button, Icon } from '../pillbox/ui';
import { FieldShell, inputBorder } from './field-shell';

const S = Strings.elderlyForm;
const DATE_INPUT_MAX_LENGTH = 10; // MM/DD/YYYY

/**
 * Date as typed text (the caller masks and parses it) plus a calendar button for the native picker.
 * Same platform split as pillbox/time-field.tsx: Android dialog, iOS inline with Batal/Pilih, web typing only.
 */
export function DateField({
  label,
  required,
  text,
  onChangeText,
  pickerValue,
  onPick,
  minimumDate,
  maximumDate,
  placeholder,
  hint,
  error,
}: {
  label: string;
  required?: boolean;
  text: string;
  onChangeText: (text: string) => void;
  /** Where the picker opens (the current value, or a sensible default). */
  pickerValue: Date;
  onPick: (date: Date) => void;
  minimumDate?: Date;
  maximumDate?: Date;
  placeholder?: string;
  hint?: string | null;
  error?: string | null;
}) {
  const [picking, setPicking] = useState(false);
  const [pending, setPending] = useState(pickerValue);
  const accent = tokens.colors.primary.DEFAULT;

  const open = () => {
    setPending(pickerValue);
    setPicking(true);
  };
  const close = () => setPicking(false);

  return (
    <FieldShell label={label} required={required} hint={hint} error={error}>
      <View className={`min-h-[52px] flex-row items-center rounded-2xl border bg-surface ${inputBorder(error)}`}>
        <TextInput
          className="min-h-[52px] flex-1 px-4 text-body text-ink"
          value={text}
          onChangeText={onChangeText}
          placeholder={placeholder}
          placeholderTextColor={tokens.colors.ink.subtle}
          keyboardType="number-pad"
          maxLength={DATE_INPUT_MAX_LENGTH}
          accessibilityLabel={label}
          accessibilityHint={S.birthDateHint}
        />
        {Platform.OS !== 'web' && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={S.birthDatePick}
            onPress={picking ? close : open}
            className="min-h-[44px] min-w-[44px] items-center justify-center px-3 active:opacity-75">
            <Icon name="calendar-outline" size={22} color={tokens.colors.primary.DEFAULT} />
          </Pressable>
        )}
      </View>

      {picking && Platform.OS === 'android' && (
        <DateTimePicker
          value={pending}
          mode="date"
          presentation="dialog"
          minimumDate={minimumDate}
          maximumDate={maximumDate}
          accentColor={accent}
          positiveButton={{ label: S.pickerConfirm }}
          negativeButton={{ label: S.pickerCancel }}
          onValueChange={(_event, date) => {
            close();
            onPick(date);
          }}
          onDismiss={close}
        />
      )}

      {picking && Platform.OS === 'ios' && (
        <View className="gap-3 rounded-2xl border border-line bg-surface p-3">
          <DateTimePicker
            value={pending}
            mode="date"
            display="spinner"
            minimumDate={minimumDate}
            maximumDate={maximumDate}
            accentColor={accent}
            onValueChange={(_event, date) => setPending(date)}
          />
          <View className="flex-row gap-3">
            <View className="flex-1">
              <Button label={S.pickerCancel} variant="secondary" onPress={close} />
            </View>
            <View className="flex-1">
              <Button
                label={S.pickerConfirm}
                icon="checkmark"
                onPress={() => {
                  close();
                  onPick(pending);
                }}
              />
            </View>
          </View>
        </View>
      )}
    </FieldShell>
  );
}
