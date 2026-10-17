// Modal dialogs for the dashboard. React Native's Alert.alert does nothing on web
// (react-native-web ships it as an empty function), so confirmations use these instead: they
// look and behave the same on Android, iOS and web.

import type { ReactNode } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, Text, View } from 'react-native';

import { Button, IconBadge, type IconName, type Tone } from './ui';

export type DialogTone = 'danger' | 'warning' | 'success' | 'primary';

const TONE: Record<DialogTone, { badge: Tone; button: 'danger' | 'warning' | 'success' | 'primary' }> = {
  danger: { badge: 'missed', button: 'danger' },
  warning: { badge: 'late', button: 'warning' },
  success: { badge: 'ontime', button: 'success' },
  primary: { badge: 'primary', button: 'primary' },
};

/** Backdrop + card. Tapping outside, Android back and Escape (web) cancel, except while busy. */
export function Dialog({
  visible,
  busy = false,
  onCancel,
  children,
}: {
  visible: boolean;
  busy?: boolean;
  onCancel: () => void;
  children: ReactNode;
}) {
  const cancel = () => {
    if (!busy) onCancel();
  };
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={cancel}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} className="flex-1">
        <Pressable className="flex-1 items-center justify-center bg-black/40 px-6" onPress={cancel} accessibilityLabel="Tutup">
          {/* Taps inside the card must not close it. */}
          <Pressable
            className="w-full max-w-[420px] gap-4 rounded-3xl bg-surface p-5"
            onPress={() => undefined}
            accessible={false}
            accessibilityViewIsModal>
            {children}
          </Pressable>
        </Pressable>
      </KeyboardAvoidingView>
    </Modal>
  );
}

/** Icon, title and message at the top of a dialog. */
export function DialogHeader({ icon, tone, title, message }: { icon?: IconName; tone: DialogTone; title: string; message?: string }) {
  return (
    <View className="gap-3">
      {icon && <IconBadge icon={icon} tone={TONE[tone].badge} size="lg" />}
      <Text className="text-heading font-bold text-ink" accessibilityRole="header">
        {title}
      </Text>
      {message ? <Text className="text-body text-ink">{message}</Text> : null}
    </View>
  );
}

/** Cancel + confirm buttons side by side. */
export function DialogActions({
  tone,
  confirmLabel,
  cancelLabel = 'Batal',
  busy = false,
  confirmDisabled = false,
  onConfirm,
  onCancel,
}: {
  tone: DialogTone;
  confirmLabel: string;
  cancelLabel?: string;
  busy?: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <View className="flex-row gap-2">
      <View className="flex-1">
        <Button label={cancelLabel} variant="secondary" onPress={onCancel} disabled={busy} />
      </View>
      <View className="flex-1">
        <Button label={confirmLabel} variant={TONE[tone].button} onPress={onConfirm} disabled={confirmDisabled} loading={busy} />
      </View>
    </View>
  );
}

export type ConfirmRequest = {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  tone: DialogTone;
  icon?: IconName;
  /** Runs when confirmed; the dialog shows a spinner until it settles, then closes. */
  onConfirm: () => Promise<void> | void;
};

/** "Are you sure?" dialog. `request` null = hidden. */
export function ConfirmDialog({
  request,
  busy,
  onConfirm,
  onCancel,
}: {
  request: ConfirmRequest | null;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Dialog visible={request !== null} busy={busy} onCancel={onCancel}>
      {request && (
        <>
          <DialogHeader icon={request.icon} tone={request.tone} title={request.title} message={request.message} />
          <DialogActions
            tone={request.tone}
            confirmLabel={request.confirmLabel}
            cancelLabel={request.cancelLabel}
            busy={busy}
            onConfirm={onConfirm}
            onCancel={onCancel}
          />
        </>
      )}
    </Dialog>
  );
}
