// Asks for the 4-digit device PIN before a sensitive pillbox command ("Buka bilik sekarang").

import { useState } from 'react';
import { TextInput } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';
import { DEVICE_PIN_PATTERN } from '@root/lib/devices';

import { Dialog, DialogActions, DialogHeader } from './dialog';

const PIN_LENGTH = 4;

export function PinPrompt({
  visible,
  title,
  message,
  confirmLabel,
  busy,
  onSubmit,
  onCancel,
}: {
  visible: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  busy: boolean;
  onSubmit: (pin: string) => void;
  onCancel: () => void;
}) {
  const [pin, setPin] = useState('');
  // The PIN never outlives the prompt: closing it (success, cancel or error) clears it.
  const [wasVisible, setWasVisible] = useState(visible);
  if (visible !== wasVisible) {
    setWasVisible(visible);
    if (!visible) setPin('');
  }
  const valid = DEVICE_PIN_PATTERN.test(pin);
  // Enter while a request is running would send the PIN (and count a wrong one) twice.
  const submit = () => {
    if (valid && !busy) onSubmit(pin);
  };
  const close = () => {
    setPin('');
    onCancel();
  };

  return (
    <Dialog visible={visible} busy={busy} onCancel={close}>
      <DialogHeader icon="lock-open-outline" tone="warning" title={title} message={message} />
      <TextInput
        className="min-h-[52px] rounded-2xl border border-line-strong bg-surface px-4 text-body text-ink"
        placeholder={Strings.pinPrompt.placeholder}
        placeholderTextColor={tokens.colors.ink.subtle}
        accessibilityLabel={Strings.pinPrompt.a11y}
        value={pin}
        editable={!busy}
        onChangeText={(v) => setPin(v.replace(/\D/g, '').slice(0, PIN_LENGTH))}
        keyboardType="number-pad"
        secureTextEntry
        autoFocus
        onSubmitEditing={submit}
      />
      <DialogActions
        tone="warning"
        confirmLabel={confirmLabel}
        busy={busy}
        confirmDisabled={!valid}
        onConfirm={submit}
        onCancel={close}
      />
    </Dialog>
  );
}
