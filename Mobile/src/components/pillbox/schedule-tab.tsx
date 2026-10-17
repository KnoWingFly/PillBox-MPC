import { ActivityIndicator, Pressable, ScrollView, Switch, Text, View } from 'react-native';

import * as tokens from '@/theme/tokens';
import * as api from '@root/lib/api';
import {
  findAllDuplicates,
  findDuplicateSlot,
  hasPassedToday,
  SCHEDULE_TIMEZONE_LABEL,
} from '@root/lib/schedule-time';
import type { Slot, SlotId } from '@root/lib/types';

import {
  COLUMN_DEFAULT_TIMES,
  COLUMNS,
  columnIndex,
  isDraftDirty,
  isSlotActive,
  isSlotChanged,
  ROWS,
  slotTitle,
  TOLERANCE_OPTIONS,
} from './helpers';
import { TimeField } from './time-field';
import { Button, Card, Chip, Divider, Icon, InfoRow, LoadErrorBox, ScreenHeader, StatusPill } from './ui';

function duplicateMessage(minutes: number, other: SlotId): string {
  return `Jam ${api.formatTime(minutes)} sudah dipakai slot ${other} (${slotTitle(other)}). Pilih jam lain.`;
}

function SlotCell({
  slot,
  selected,
  changed,
  conflict,
  onPress,
}: {
  slot: Slot;
  selected: boolean;
  changed: boolean;
  conflict: boolean;
  onPress: () => void;
}) {
  const active = isSlotActive(slot);
  const empty = slot.timeMinutes === null;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Slot ${slot.id}, ${empty ? 'kosong' : api.formatTime(slot.timeMinutes)}, ${
        active ? 'aktif' : 'nonaktif'
      }${changed ? ', belum disimpan' : ''}${conflict ? ', jam bentrok dengan slot lain' : ''}`}
      accessibilityState={{ selected }}
      onPress={onPress}
      className={`min-h-[84px] flex-1 items-center justify-center gap-1 rounded-2xl border-2 px-1 py-2 active:opacity-75 ${
        conflict
          ? 'border-missed-solid bg-missed-soft'
          : selected
            ? 'border-primary bg-primary-light'
            : active
              ? 'border-line bg-surface'
              : 'border-line bg-surface-muted'
      }`}>
      <View className="flex-row items-center gap-1">
        <Text className="text-body-sm font-semibold text-ink-muted">{slot.id}</Text>
        {changed && <View className="h-2 w-2 rounded-full bg-late-solid" />}
      </View>
      <Text className={`text-title ${empty ? 'text-ink-subtle' : active ? 'font-bold text-ink' : 'font-semibold text-ink-muted'}`}>
        {empty ? '—' : api.formatTime(slot.timeMinutes)}
      </Text>
      <View className={`h-1.5 w-6 rounded-full ${active ? 'bg-ontime-solid' : 'bg-line'}`} />
    </Pressable>
  );
}

function SlotEditor({
  slot,
  allSlots,
  conflictWith,
  now,
  testing,
  onChange,
  onTest,
}: {
  slot: Slot;
  /** The whole draft, for the duplicate-time check. */
  allSlots: Slot[];
  /** Enabled slot that already uses this slot's time, if any. */
  conflictWith: SlotId | null;
  now: number;
  testing: boolean;
  onChange: (patch: Partial<Slot>) => void;
  onTest: () => void;
}) {
  const defaultTime = COLUMN_DEFAULT_TIMES[columnIndex(slot.id)];

  // Duplicates only matter for slots that will ring; a disabled slot may share a time.
  const validate = (minutes: number) => {
    const other = slot.enabled || slot.timeMinutes === null ? findDuplicateSlot(allSlots, slot.id, minutes) : null;
    return other ? duplicateMessage(minutes, other) : null;
  };

  // Picking a time for an empty slot also turns it on, like the switch does; otherwise it would be
  // saved inactive and the pillbox would ignore it.
  const setTime = (minutes: number) =>
    onChange(slot.timeMinutes === null ? { timeMinutes: minutes, enabled: true } : { timeMinutes: minutes });

  const timeHint =
    slot.enabled && slot.timeMinutes !== null
      ? hasPassedToday(slot.timeMinutes, now)
        ? `Sudah lewat hari ini. Pengingat berikutnya besok pukul ${api.formatTime(slot.timeMinutes)} ${SCHEDULE_TIMEZONE_LABEL}.`
        : `Pengingat berikutnya hari ini pukul ${api.formatTime(slot.timeMinutes)} ${SCHEDULE_TIMEZONE_LABEL}.`
      : null;

  return (
    <Card
      title={`Slot ${slot.id}`}
      subtitle={slotTitle(slot.id)}
      icon="medkit-outline"
      right={<StatusPill label={isSlotActive(slot) ? 'Aktif' : 'Nonaktif'} tone={isSlotActive(slot) ? 'ontime' : 'neutral'} />}>
      <View className="min-h-[48px] flex-row items-center justify-between gap-3 rounded-2xl bg-canvas px-4">
        <Text className="text-body font-semibold text-ink">Aktifkan pengingat</Text>
        <Switch
          accessibilityLabel={`Aktifkan jadwal slot ${slot.id}`}
          value={slot.enabled}
          onValueChange={(enabled) =>
            onChange(enabled && slot.timeMinutes === null ? { enabled, timeMinutes: defaultTime } : { enabled })
          }
          trackColor={{ false: tokens.colors.line.strong, true: tokens.colors.primary.DEFAULT }}
          thumbColor="#FFFFFF"
        />
      </View>

      <View className="gap-2">
        <TimeField
          label={`Waktu minum (24 jam, ${SCHEDULE_TIMEZONE_LABEL})`}
          value={slot.timeMinutes}
          fallback={defaultTime}
          externalError={conflictWith && slot.timeMinutes !== null ? duplicateMessage(slot.timeMinutes, conflictWith) : null}
          validate={validate}
          onChange={setTime}
        />
        {timeHint && (
          <View className="flex-row items-start gap-2">
            <Icon name="time-outline" size={18} color={tokens.colors.ink.muted} />
            <Text className="flex-1 text-body-sm text-ink-muted">{timeHint}</Text>
          </View>
        )}
      </View>

      <View className="gap-2">
        <Text className="text-body font-semibold text-ink">Toleransi keterlambatan</Text>
        <View className="flex-row flex-wrap gap-2">
          {TOLERANCE_OPTIONS.map((opt) => (
            <Chip
              key={opt.value}
              label={opt.label}
              selected={slot.toleranceMinutes === opt.value}
              onPress={() => onChange({ toleranceMinutes: opt.value })}
            />
          ))}
        </View>
      </View>

      <Divider />
      <InfoRow icon="file-tray-stacked-outline" label="Stok" value={`${slot.stock} dari ${slot.capacity} dosis`} />
      <Button label="Tes Pengingat di Pillbox" icon="volume-high-outline" variant="secondary" loading={testing} onPress={onTest} />
    </Card>
  );
}

export function ScheduleTab({
  draft,
  saved,
  selectedId,
  onSelect,
  onChangeSlot,
  loadError,
  onRetry,
  now,
  testing,
  onTest,
  saving,
  onSave,
  onDiscard,
}: {
  draft: Slot[];
  saved: Slot[];
  selectedId: SlotId | null;
  onSelect: (id: SlotId) => void;
  onChangeSlot: (id: SlotId, patch: Partial<Slot>) => void;
  loadError: boolean;
  onRetry: () => void;
  now: number;
  testing: boolean;
  onTest: (id: SlotId) => void;
  saving: boolean;
  onSave: () => void;
  onDiscard: () => void;
}) {
  const dirty = isDraftDirty(draft, saved);
  const selected = draft.find((s) => s.id === selectedId);
  const conflicts = findAllDuplicates(draft);
  const activeCount = draft.filter(isSlotActive).length;

  return (
    <View className="flex-1">
      <ScrollView contentContainerClassName="gap-4 px-4 pb-8 pt-4" keyboardShouldPersistTaps="handled">
        <ScreenHeader
          title="Jadwal Obat"
          subtitle={draft.length ? `${activeCount} dari ${draft.length} bilik aktif · ketuk bilik untuk mengubah` : undefined}
        />

        <Card>
          {draft.length === 0 && loadError ? (
            <LoadErrorBox text="Gagal memuat jadwal. Periksa koneksi lalu coba lagi." onRetry={onRetry} />
          ) : draft.length === 0 ? (
            <ActivityIndicator color={tokens.colors.primary.DEFAULT} accessibilityLabel="Memuat jadwal" />
          ) : (
            <View className="gap-3">
              <View className="flex-row gap-2">
                {COLUMNS.map((c) => (
                  <View key={c.label} className="flex-1 items-center gap-0.5">
                    <Icon name={c.icon} size={18} color={tokens.colors.ink.muted} />
                    <Text className="text-body-sm font-semibold text-ink-muted">{c.label}</Text>
                  </View>
                ))}
              </View>
              {ROWS.map((row) => (
                <View key={row.key} className="gap-2">
                  <Text className="text-body-sm font-semibold text-ink-muted">
                    {row.key} · {row.label}
                  </Text>
                  <View className="flex-row gap-2">
                    {draft
                      .filter((s) => s.id.startsWith(row.key))
                      .map((slot) => (
                        <SlotCell
                          key={slot.id}
                          slot={slot}
                          selected={slot.id === selectedId}
                          changed={isSlotChanged(slot, saved)}
                          conflict={conflicts.has(slot.id)}
                          onPress={() => onSelect(slot.id)}
                        />
                      ))}
                  </View>
                </View>
              ))}
            </View>
          )}
        </Card>

        {selected ? (
          <SlotEditor
            // Remount per slot so typing / picker state never carries over to another slot.
            key={selected.id}
            slot={selected}
            allSlots={draft}
            conflictWith={conflicts.get(selected.id) ?? null}
            now={now}
            testing={testing}
            onChange={(patch) => onChangeSlot(selected.id, patch)}
            onTest={() => onTest(selected.id)}
          />
        ) : (
          draft.length > 0 && (
            <View className="flex-row items-center gap-3 rounded-2xl bg-primary-light p-4">
              <Icon name="hand-left-outline" size={22} color={tokens.colors.primary.dark} />
              <Text className="flex-1 text-body text-primary-dark">Pilih salah satu bilik di atas untuk mengatur jam minum.</Text>
            </View>
          )
        )}
      </ScrollView>

      {/* Save bar: only while there are unsaved edits. */}
      {dirty && (
        <View className="gap-2 border-t border-line bg-surface px-4 pb-3 pt-3">
          {conflicts.size > 0 ? (
            <Text className="text-body-sm font-semibold text-missed-fg" accessibilityRole="alert">
              Jam bentrok di {[...conflicts.keys()].join(', ')}. Ubah salah satunya sebelum menyimpan.
            </Text>
          ) : (
            <Text className="text-body-sm text-ink-muted">Ada perubahan yang belum dikirim ke Pillbox.</Text>
          )}
          <View className="flex-row gap-3">
            <View className="flex-1">
              <Button label="Batalkan" variant="secondary" disabled={saving} onPress={onDiscard} />
            </View>
            <View className="flex-[2]">
              <Button
                label="Simpan ke Pillbox"
                icon="cloud-upload-outline"
                loading={saving}
                disabled={conflicts.size > 0}
                onPress={onSave}
              />
            </View>
          </View>
        </View>
      )}
    </View>
  );
}
