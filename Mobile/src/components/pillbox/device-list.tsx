// "Pillbox Anda" list (Perangkat tab), the rename dialog and the active-pillbox switcher.
import { useState } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';

import * as tokens from '@/theme/tokens';
import { canEdit, canUnpair, PILLBOX_NAME_MAX, type Pillbox } from '@root/lib/devices';

import { Dialog, DialogActions, DialogHeader } from './dialog';
import { formatRelative, LOW_BATTERY_PERCENT } from './helpers';
import { Button, Card, Chip, Icon, StatusPill } from './ui';

const ROLE_LABEL = { OWNER: 'Pemilik', ADMIN: 'Admin', PEMANTAU: 'Pemantau' } as const;

function PillboxRow({
  pillbox,
  active,
  now,
  onSelect,
  onRename,
  onRemove,
  onHide,
}: {
  pillbox: Pillbox;
  active: boolean;
  now: number;
  onSelect: () => void;
  onRename: () => void;
  onRemove: () => void;
  onHide: () => void;
}) {
  const battery = pillbox.batteryPercent;
  return (
    <View
      className={`gap-3 rounded-2xl border p-4 ${active ? 'border-primary bg-primary-light' : 'border-line bg-surface'}`}
      accessibilityLabel={`${pillbox.name}${active ? ', pillbox aktif' : ''}`}>
      <View className="flex-row items-start justify-between gap-2">
        <View className="flex-1 gap-0.5">
          <Text className="text-body font-semibold text-ink" numberOfLines={1}>
            {pillbox.name}
          </Text>
          <Text className="text-caption text-ink-muted">
            {pillbox.code}
            {pillbox.elderlyName ? ` · ${pillbox.elderlyName}` : ''}
            {pillbox.myRole ? ` · ${ROLE_LABEL[pillbox.myRole]}` : ''}
          </Text>
        </View>
        {active && <StatusPill label="Aktif" tone="primary" icon="checkmark-circle" />}
      </View>
      <View className="flex-row flex-wrap items-center gap-2">
        <StatusPill
          label={
            pillbox.online
              ? 'Terhubung'
              : pillbox.lastSeenAt
                ? `Offline · ${formatRelative(pillbox.lastSeenAt, now)}`
                : 'Belum pernah terhubung'
          }
          tone={pillbox.online ? 'ontime' : 'neutral'}
        />
        {battery !== null && (
          <StatusPill
            label={`Baterai ${battery}%`}
            tone={battery <= LOW_BATTERY_PERCENT ? 'missed' : 'battery'}
            icon={battery <= LOW_BATTERY_PERCENT ? 'battery-dead-outline' : 'battery-half-outline'}
          />
        )}
      </View>
      <View className="flex-row flex-wrap gap-2">
        {!active && <Button label="Jadikan aktif" size="sm" icon="swap-horizontal" onPress={onSelect} />}
        {canEdit(pillbox.myRole) && <Button label="Ubah nama" size="sm" variant="secondary" icon="create-outline" onPress={onRename} />}
        {canUnpair(pillbox.myRole) ? (
          <Button label="Hapus" size="sm" variant="danger-soft" icon="trash-outline" onPress={onRemove} />
        ) : (
          <Button label="Sembunyikan" size="sm" variant="secondary" icon="eye-off-outline" onPress={onHide} />
        )}
      </View>
    </View>
  );
}

export function PillboxListCard({
  pillboxes,
  hiddenCount,
  activeId,
  now,
  onSelect,
  onAdd,
  onRename,
  onRemove,
  onHide,
  onUnhideAll,
}: {
  pillboxes: Pillbox[];
  hiddenCount: number;
  activeId: string | null;
  now: number;
  onSelect: (pillbox: Pillbox) => void;
  onAdd: () => void;
  onRename: (pillbox: Pillbox) => void;
  onRemove: (pillbox: Pillbox) => void;
  onHide: (pillbox: Pillbox) => void;
  onUnhideAll: () => void;
}) {
  return (
    <Card title="Pillbox Anda" subtitle={`${pillboxes.length} pillbox terhubung`} icon="cube-outline">
      {pillboxes.map((p) => (
        <PillboxRow
          key={p.id}
          pillbox={p}
          active={p.id === activeId}
          now={now}
          onSelect={() => onSelect(p)}
          onRename={() => onRename(p)}
          onRemove={() => onRemove(p)}
          onHide={() => onHide(p)}
        />
      ))}
      <Button label="Tambah pillbox" icon="add-circle-outline" onPress={onAdd} />
      {hiddenCount > 0 && (
        <Button label={`Tampilkan ${hiddenCount} pillbox tersembunyi`} variant="ghost" icon="eye-outline" onPress={onUnhideAll} />
      )}
    </Card>
  );
}

/** Rename dialog. Mount it only while open; `onSave` resolves when the request settles. */
export function RenamePillboxDialog({
  pillbox,
  onSave,
  onCancel,
}: {
  pillbox: Pillbox;
  onSave: (name: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState(pillbox.name);
  const [busy, setBusy] = useState(false);
  const trimmed = name.trim();
  const valid = trimmed.length > 0 && trimmed.length <= PILLBOX_NAME_MAX && trimmed !== pillbox.name;

  const save = async () => {
    if (!valid) return;
    setBusy(true);
    try {
      await onSave(trimmed);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog visible busy={busy} onCancel={onCancel}>
      <DialogHeader icon="create-outline" tone="primary" title="Ubah nama pillbox" message={pillbox.code} />
      <TextInput
        className="min-h-[52px] rounded-2xl border border-line-strong bg-surface px-4 text-body text-ink"
        placeholderTextColor={tokens.colors.ink.subtle}
        value={name}
        onChangeText={setName}
        maxLength={PILLBOX_NAME_MAX}
        autoFocus
        editable={!busy}
        accessibilityLabel="Nama pillbox"
        onSubmitEditing={() => void save()}
      />
      <DialogActions tone="primary" confirmLabel="Simpan" busy={busy} confirmDisabled={!valid} onConfirm={() => void save()} onCancel={onCancel} />
    </Dialog>
  );
}

/** Active-pillbox chips above every tab; shown only when there is more than one pillbox. */
export function PillboxSwitcher({
  pillboxes,
  activeId,
  onSelect,
}: {
  pillboxes: Pillbox[];
  activeId: string | null;
  onSelect: (pillbox: Pillbox) => void;
}) {
  if (pillboxes.length < 2) return null;
  return (
    <View className="border-b border-line bg-surface">
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerClassName="items-center gap-2 px-4 py-2">
        <Icon name="cube-outline" size={18} color={tokens.colors.ink.muted} />
        {pillboxes.map((p) => (
          <Chip key={p.id} label={p.name} selected={p.id === activeId} onPress={() => p.id !== activeId && onSelect(p)} />
        ))}
      </ScrollView>
    </View>
  );
}
