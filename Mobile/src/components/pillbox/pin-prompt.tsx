// Asks for the 4-digit device PIN before a sensitive pillbox command ("Buka bilik sekarang").

import { useState } from 'react';
import { TextInput } from 'react-native';

import * as tokens from '@/theme/tokens';

import { Dialog, DialogActions, DialogHeader } from './dialog';

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
  const valid = /^\d{4}$/.test(pin);
  const close = () => {
    setPin('');
    onCancel();
  };

  return (
    <Dialog visible={visible} busy={busy} onCancel={close}>
      <DialogHeader icon="lock-open-outline" tone="warning" title={title} message={message} />
      <TextInput
        className="min-h-[52px] rounded-2xl border border-line-strong bg-surface px-4 text-body text-ink"
        placeholder="PIN perangkat (4 digit)"
        placeholderTextColor={tokens.colors.ink.subtle}
        accessibilityLabel="PIN perangkat, 4 digit"
        value={pin}
        onChangeText={(v) => setPin(v.replace(/\D/g, '').slice(0, 4))}
        keyboardType="number-pad"
        secureTextEntry
        autoFocus
        onSubmitEditing={() => valid && onSubmit(pin)}
      />
      <DialogActions
        tone="warning"
        confirmLabel={confirmLabel}
        busy={busy}
        confirmDisabled={!valid}
        onConfirm={() => onSubmit(pin)}
        onCancel={close}
      />
    </Dialog>
  );
}
