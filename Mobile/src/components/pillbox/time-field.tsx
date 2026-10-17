import { DateTimePicker } from '@expo/ui/community/datetime-picker';
import { useState } from 'react';
import { Platform, Pressable, Text, TextInput, View } from 'react-native';

import * as tokens from '@/theme/tokens';
import {
  maskTimeInput,
  minutesToPickerDate,
  parseTimeInput,
  pickerDateToMinutes,
} from '@root/lib/schedule-time';

import { Button, Icon } from './ui';

function formatHHMM(minutes: number): string {
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
}

/**
 * 24h time input. The main control is the native picker ("Pilih jam"); tapping the big time lets
 * the user type HH:MM instead. `validate` returns an error for a value that parses but is not
 * allowed (e.g. already used by another slot); such a value is rejected and `onChange` is not called.
 */
export function TimeField({
  label,
  value,
  fallback,
  externalError,
  validate,
  onChange,
}: {
  label: string;
  /** Minutes since midnight, or null when not set yet. */
  value: number | null;
  /** Where the picker starts when `value` is null. */
  fallback: number;
  /** Error from outside this field (e.g. a conflict caused by enabling another slot). */
  externalError?: string | null;
  validate: (minutes: number) => string | null;
  onChange: (minutes: number) => void;
}) {
  const [mode, setMode] = useState<'view' | 'typing' | 'picking'>('view');
  const [text, setText] = useState('');
  const [pending, setPending] = useState<Date>(() => minutesToPickerDate(value ?? fallback));
  const [error, setError] = useState<string | null>(null);

  const display = value === null ? '--:--' : formatHHMM(value);
  const shownError = error ?? externalError ?? null;
  const accent = tokens.colors.primary.DEFAULT;

  const apply = (minutes: number): boolean => {
    const problem = validate(minutes);
    if (problem) {
      setError(problem);
      return false;
    }
    setError(null);
    onChange(minutes);
    return true;
  };

  const startTyping = () => {
    setText(value === null ? '' : formatHHMM(value));
    setError(null);
    setMode('typing');
  };

  const commitTyping = () => {
    const parsed = parseTimeInput(text);
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    if (apply(parsed.minutes)) setMode('view');
  };

  const openPicker = () => {
    setPending(minutesToPickerDate(value ?? fallback));
    setError(null);
    setMode('picking');
  };

  const closePicker = () => setMode('view');

  return (
    <View className="gap-2">
      <Text className="text-body font-semibold text-ink">{label}</Text>

      {mode === 'typing' ? (
        <View className="gap-3">
          <TextInput
            autoFocus
            value={text}
            onChangeText={(raw) => {
              setText(maskTimeInput(raw));
              setError(null);
            }}
            onSubmitEditing={commitTyping}
            keyboardType="number-pad"
            returnKeyType="done"
            maxLength={5}
            placeholder="JJ:MM"
            placeholderTextColor={tokens.colors.ink.subtle}
            accessibilityLabel={`${label}, ketik jam format JJ:MM`}
            accessibilityHint="Contoh 07:30. Format 24 jam."
            className={`min-h-[72px] rounded-2xl border-2 bg-surface px-4 text-center text-time font-bold tracking-widest text-ink ${
              shownError ? 'border-missed-solid' : 'border-primary'
            }`}
          />
          <View className="flex-row gap-3">
            <View className="flex-1">
              <Button
                label="Batal"
                variant="secondary"
                onPress={() => {
                  setError(null);
                  setMode('view');
                }}
                accessibilityLabel="Batal mengetik jam"
              />
            </View>
            <View className="flex-1">
              <Button label="Pakai jam" icon="checkmark" onPress={commitTyping} />
            </View>
          </View>
        </View>
      ) : (
        <View className="flex-row items-stretch gap-3">
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`${label} ${value === null ? 'belum diatur' : display}. Ketuk untuk mengetik jam.`}
            onPress={startTyping}
            className={`min-h-[72px] flex-1 flex-row items-center justify-between rounded-2xl border-2 bg-surface px-4 active:opacity-75 ${
              shownError ? 'border-missed-solid' : 'border-line'
            }`}>
            <Text className="text-time font-bold tracking-wide text-ink">{display}</Text>
            <View className="items-center">
              <Icon name="create-outline" size={20} color={tokens.colors.ink.muted} />
              <Text className="text-caption text-ink-muted">Ketik</Text>
            </View>
          </Pressable>
          {Platform.OS !== 'web' && (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Pilih jam dengan pemilih waktu"
              onPress={mode === 'picking' ? closePicker : openPicker}
              className="min-h-[72px] w-24 items-center justify-center gap-1 rounded-2xl bg-primary active:opacity-75">
              <Icon name="time-outline" size={24} color="#FFFFFF" />
              <Text className="text-body-sm font-semibold text-white">Pilih jam</Text>
            </Pressable>
          )}
        </View>
      )}

      {mode === 'picking' && Platform.OS === 'android' && (
        // Android: a modal dialog that opens on mount; unmounted again on confirm or cancel.
        <DateTimePicker
          value={pending}
          mode="time"
          is24Hour
          presentation="dialog"
          accentColor={accent}
          positiveButton={{ label: 'Pilih' }}
          negativeButton={{ label: 'Batal' }}
          onValueChange={(_event, date) => {
            closePicker();
            apply(pickerDateToMinutes(date));
          }}
          onDismiss={closePicker}
        />
      )}

      {mode === 'picking' && Platform.OS === 'ios' && (
        // iOS: always inline. en_GB forces the 24h wheel; the value is applied only on "Pilih".
        <View className="gap-3 rounded-2xl border border-line bg-surface p-3">
          <DateTimePicker
            value={pending}
            mode="time"
            display="spinner"
            locale="en_GB"
            accentColor={accent}
            onValueChange={(_event, date) => setPending(date)}
          />
          <View className="flex-row gap-3">
            <View className="flex-1">
              <Button label="Batal" variant="secondary" onPress={closePicker} />
            </View>
            <View className="flex-1">
              <Button
                label="Pilih"
                icon="checkmark"
                onPress={() => {
                  if (apply(pickerDateToMinutes(pending))) closePicker();
                }}
              />
            </View>
          </View>
        </View>
      )}

      {shownError && (
        <View className="flex-row items-start gap-2" accessibilityRole="alert" accessibilityLiveRegion="polite">
          <Icon name="alert-circle" size={18} color={tokens.colors.missed.fg} />
          <Text className="flex-1 text-body-sm font-semibold text-missed-fg">{shownError}</Text>
        </View>
      )}
    </View>
  );
}
