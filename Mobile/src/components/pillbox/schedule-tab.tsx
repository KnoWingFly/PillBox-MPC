import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Switch, Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';
import * as api from '@root/lib/api';
import {
  findAllConflicts,
  findSlotConflict,
  hasPassedToday,
  type SlotConflict,
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
import { AlarmButton, type AlarmControl } from './alarm-button';
import { TimeField } from './time-field';
import { ProgressBar } from './blocks';
import { Button, Card, Chip, Icon, IconBadge, LoadErrorBox, ScreenHeader, StatusPill, type IconName } from './ui';

const S = Strings.schedule;

function conflictMessage(minutes: number, conflict: SlotConflict, slots: Slot[]): string {
  if (conflict.kind === 'same_time') {
    return S.conflictSameTime(api.formatTime(minutes), conflict.other, slotTitle(conflict.other));
  }
  const otherTime = slots.find((s) => s.id === conflict.other)?.timeMinutes ?? null;
  return S.conflictTooClose(conflict.other, api.formatTime(otherTime), conflict.gapMinutes);
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
      accessibilityLabel={S.slotA11y(slot.id, empty ? null : api.formatTime(slot.timeMinutes), active, changed, conflict)}
      accessibilityState={{ selected }}
      onPress={onPress}
      className={`min-h-[96px] flex-1 items-center justify-center gap-1 rounded-3xl border-2 px-1 py-2 active:opacity-75 ${
        conflict
          ? 'border-missed-solid bg-missed-soft'
          : selected
            ? 'border-primary bg-primary-light'
            : active
              ? 'border-surface bg-surface'
              : 'border-dashed border-line-strong bg-transparent'
      }`}
      style={active && !selected && !conflict ? { boxShadow: tokens.shadow.card } : undefined}>
      <View className="flex-row items-center gap-1">
        <View className="rounded-full bg-canvas px-2 py-0.5">
          <Text className="text-caption font-bold text-ink-muted">{slot.id}</Text>
        </View>
        {changed && <View className="h-2 w-2 rounded-full bg-late-solid" />}
      </View>
      {empty ? (
        <Icon name="add-circle-outline" size={24} color={tokens.colors.ink.subtle} />
      ) : (
        <Text className={`text-title ${active ? 'font-bold text-ink' : 'font-semibold text-ink-muted'}`}>
          {api.formatTime(slot.timeMinutes)}
        </Text>
      )}
      <Text className={`text-caption font-semibold ${active ? 'text-ontime-fg' : 'text-ink-muted'}`}>
        {empty ? S.empty : active ? S.active : S.inactive}
      </Text>
    </Pressable>
  );
}

function SlotEditor({
  slot,
  allSlots,
  conflictWith,
  now,
  timezoneLabel,
  canEdit,
  testing,
  alarm,
  onChange,
  onTest,
}: {
  slot: Slot;
  /** The whole draft, for the duplicate-time check. */
  allSlots: Slot[];
  /** Enabled slot that already uses this slot's time, if any. */
  conflictWith: SlotConflict | null;
  now: number;
  /** "WIB" etc.: the pillbox's timezone, the one the times are in. */
  timezoneLabel: string;
  /** false = PEMANTAU: everything is shown read-only and the test alarm is hidden. */
  canEdit: boolean;
  testing: boolean;
  alarm: AlarmControl;
  onChange: (patch: Partial<Slot>) => void;
  onTest: () => void;
}) {
  const defaultTime = COLUMN_DEFAULT_TIMES[columnIndex(slot.id)];

  // Conflicts only matter for slots that will ring; a disabled slot may share a time.
  const validate = (minutes: number) => {
    const conflict =
      slot.enabled || slot.timeMinutes === null ? findSlotConflict(allSlots, slot.id, minutes, slot.toleranceMinutes) : null;
    return conflict ? conflictMessage(minutes, conflict, allSlots) : null;
  };

  // Picking a time for an empty slot also turns it on, like the switch does; otherwise it would be
  // saved inactive and the pillbox would ignore it.
  const setTime = (minutes: number) =>
    onChange(slot.timeMinutes === null ? { timeMinutes: minutes, enabled: true } : { timeMinutes: minutes });

  const timeHint =
    slot.enabled && slot.timeMinutes !== null
      ? hasPassedToday(slot.timeMinutes, now)
        ? S.nextTomorrow(api.formatTime(slot.timeMinutes), timezoneLabel)
        : S.nextToday(api.formatTime(slot.timeMinutes), timezoneLabel)
      : null;

  const active = isSlotActive(slot);

  return (
    <Card>
      <View className="flex-row items-center gap-2">
        <View className="rounded-full bg-primary-light px-3 py-1">
          <Text className="text-body-sm font-bold text-primary-dark">{S.slotBadge(slot.id)}</Text>
        </View>
        <View className="flex-1 flex-row">
          <StatusPill label={active ? S.compartmentActive : S.compartmentInactive} tone={active ? 'ontime' : 'neutral'} />
        </View>
        <Switch
          accessibilityLabel={S.enableA11y(slot.id)}
          disabled={!canEdit}
          value={slot.enabled}
          onValueChange={(enabled) =>
            onChange(enabled && slot.timeMinutes === null ? { enabled, timeMinutes: defaultTime } : { enabled })
          }
          trackColor={{ false: tokens.colors.line.strong, true: tokens.colors.primary.DEFAULT }}
          thumbColor={tokens.colors.surface.DEFAULT}
        />
      </View>
      <View>
        <Text className="text-heading font-bold text-ink" accessibilityRole="header">
          {`${api.getSlotColumnLabel(slot.id)} – ${api.getSlotRowLabel(slot.id)}`}
        </Text>
      </View>

      <EditorWell icon="file-tray-stacked-outline" title={S.stockTitle}>
        <Text className="text-body font-semibold text-ink">{S.stockValue(slot.stock, slot.capacity)}</Text>
        <ProgressBar percent={slot.capacity > 0 ? (slot.stock / slot.capacity) * 100 : 0} tone="primary" />
      </EditorWell>

      <EditorWell icon="alarm-outline" title={S.timeTitle}>
        {canEdit ? (
          <TimeField
            label={S.timeLabel(timezoneLabel)}
            value={slot.timeMinutes}
            fallback={defaultTime}
            externalError={conflictWith && slot.timeMinutes !== null ? conflictMessage(slot.timeMinutes, conflictWith, allSlots) : null}
            validate={validate}
            onChange={setTime}
          />
        ) : (
          <Text className="text-title font-bold text-ink" accessibilityLabel={S.timeLabel(timezoneLabel)}>
            {`${api.formatTime(slot.timeMinutes)} ${timezoneLabel}`}
          </Text>
        )}
        {timeHint && (
          <View className="flex-row items-start gap-2">
            <Icon name="time-outline" size={18} color={tokens.colors.ink.muted} />
            <Text className="flex-1 text-body-sm text-ink-muted">{timeHint}</Text>
          </View>
        )}
      </EditorWell>

      <EditorWell icon="notifications-outline" title={S.toleranceTitle}>
        <Text className="text-body-sm text-ink-muted">{S.toleranceText}</Text>
        <View className="flex-row flex-wrap gap-2">
          {TOLERANCE_OPTIONS.map((opt) => (
            <Chip
              key={opt.value}
              label={opt.label}
              selected={slot.toleranceMinutes === opt.value}
              disabled={!canEdit}
              onPress={() => onChange({ toleranceMinutes: opt.value })}
            />
          ))}
        </View>
      </EditorWell>

      {canEdit && (
        <AlarmButton
          label={S.testAlarm}
          icon="volume-high-outline"
          variant="secondary"
          starting={testing}
          onStart={onTest}
          alarm={alarm}
        />
      )}
    </Card>
  );
}

/** Nested tinted section inside the slot editor (Stok, Waktu, Toleransi). */
function EditorWell({ icon, title, children }: { icon: IconName; title: string; children: ReactNode }) {
  return (
    <View className="gap-3 rounded-3xl bg-canvas p-4">
      <View className="flex-row items-center gap-2">
        <Icon name={icon} size={20} color={tokens.colors.primary.DEFAULT} />
        <Text className="flex-1 text-body font-bold text-ink">{title}</Text>
      </View>
      {children}
    </View>
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
  timezoneLabel,
  canEdit,
  testing,
  alarm,
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
  /** Abbreviation of the pillbox's timezone, e.g. "WIB". */
  timezoneLabel: string;
  /** OWNER / ADMIN. PEMANTAU sees the schedule read-only, without test alarm or save bar. */
  canEdit: boolean;
  testing: boolean;
  alarm: AlarmControl;
  onTest: (id: SlotId) => void;
  saving: boolean;
  onSave: () => void;
  onDiscard: () => void;
}) {
  const dirty = canEdit && isDraftDirty(draft, saved);
  const selected = draft.find((s) => s.id === selectedId);
  const conflicts = findAllConflicts(draft);
  const activeCount = draft.filter(isSlotActive).length;

  return (
    <View className="flex-1">
      <ScrollView contentContainerClassName="gap-4 px-4 pb-8 pt-4" keyboardShouldPersistTaps="handled">
        <ScreenHeader
          title={S.title}
          subtitle={S.subtitle}
          right={
            draft.length > 0 ? (
              <StatusPill label={S.activeBadge(activeCount, draft.length)} tone="primary" icon="options-outline" />
            ) : undefined
          }
        />

        <Card title={S.gridTitle} subtitle={S.gridSubtitle} icon="grid-outline">
          {draft.length === 0 && loadError ? (
            <LoadErrorBox text={S.loadError} onRetry={onRetry} />
          ) : draft.length === 0 ? (
            <ActivityIndicator color={tokens.colors.primary.DEFAULT} accessibilityLabel={S.loading} />
          ) : (
            <View className="gap-3">
              <View className="flex-row gap-2">
                {COLUMNS.map((c, i) => (
                  <View key={c.label} className="flex-1 items-center gap-0.5 rounded-full bg-canvas py-3">
                    <Icon name={c.icon} size={20} color={tokens.colors.late.fg} />
                    <Text className="text-body-sm font-semibold text-ink">{c.label}</Text>
                    <Text className="text-caption text-ink-muted">{api.formatTime(COLUMN_DEFAULT_TIMES[i])}</Text>
                  </View>
                ))}
              </View>
              {ROWS.map((row) => (
                <View key={row.key} className="gap-3 rounded-3xl bg-canvas p-3">
                  <View className="flex-row items-center gap-2">
                    <View className="rounded-lg bg-surface px-2 py-0.5">
                      <Text className="text-body-sm font-bold text-ink">{S.rowLabel(row.key)}</Text>
                    </View>
                    <Text className="text-body-sm text-ink-muted">{row.label}</Text>
                  </View>
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
            timezoneLabel={timezoneLabel}
            canEdit={canEdit}
            testing={testing}
            alarm={alarm}
            onChange={(patch) => onChangeSlot(selected.id, patch)}
            onTest={() => onTest(selected.id)}
          />
        ) : (
          draft.length > 0 && (
            <View className="flex-row items-center gap-3 rounded-2xl bg-primary-light p-4">
              <Icon name="hand-left-outline" size={22} color={tokens.colors.primary.dark} />
              <Text className="flex-1 text-body text-primary-dark">{S.pickHint}</Text>
            </View>
          )
        )}

        <View className="flex-row items-start gap-3 rounded-2xl bg-surface-muted p-4">
          <IconBadge icon={canEdit ? 'shield-checkmark-outline' : 'eye-outline'} tone="neutral" size="sm" />
          <Text className="flex-1 text-body-sm text-ink-muted">{canEdit ? S.roleNote : S.readOnlyNote}</Text>
        </View>
      </ScrollView>

      {/* Save bar: only while there are unsaved edits. */}
      {dirty && (
        <View className="gap-2 bg-surface px-4 pb-3 pt-3" style={{ boxShadow: tokens.shadow.raised }}>
          {conflicts.size > 0 ? (
            <Text className="text-body-sm font-semibold text-missed-fg" accessibilityRole="alert">
              {S.conflicts([...conflicts.keys()].join(', '))}
            </Text>
          ) : (
            <Text className="text-body-sm text-ink-muted">{S.dirty}</Text>
          )}
          <View className="flex-row gap-3">
            <View className="flex-1">
              <Button label={S.discard} variant="secondary" disabled={saving} onPress={onDiscard} />
            </View>
            <View className="flex-[2]">
              <Button label={S.save} icon="sync-outline" loading={saving} disabled={conflicts.size > 0} onPress={onSave} />
            </View>
          </View>
        </View>
      )}
    </View>
  );
}
