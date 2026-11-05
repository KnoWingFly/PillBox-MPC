import { useEffect, useState, type ReactNode } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';
import * as api from '@root/lib/api';
import type { Pillbox } from '@root/lib/devices';
import type { DeviceClock } from '@root/lib/insights';
import { SLOT_IDS, type DeviceStatus, type DoseEventType, type Slot, type SlotId } from '@root/lib/types';

import { ListRow, ProgressBar, StatTile, SwitchRow } from './blocks';
import {
  deviceLook,
  formatPillboxClock,
  formatRelative,
  isSlotActive,
  batteryText,
  formatBattery,
  isLowBattery,
  pillboxClockNote,
  pillboxNow,
} from './helpers';
import { Button, Card, Chip, Icon, IconBadge, LoadErrorBox, ScreenHeader, StatusPill } from './ui';

const S = Strings.device;
/** The clock card redraws every second; the rest of the tab follows the dashboard's slower tick. */
const CLOCK_TICK_MS = 1_000;

/** Pillbox chips (switch the active one) and "Tambah". */
function PillboxChips({
  pillboxes,
  activeId,
  onSelect,
  onAdd,
}: {
  pillboxes: Pillbox[];
  activeId: string | null;
  onSelect: (pillbox: Pillbox) => void;
  onAdd?: () => void;
}) {
  if (pillboxes.length === 0 && !onAdd) return null;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerClassName="gap-2">
      {pillboxes.map((p) => (
        <Chip
          key={p.id}
          label={S.chip(p.name, p.batteryPercent)}
          selected={p.id === activeId}
          onPress={() => p.id !== activeId && onSelect(p)}
        />
      ))}
      {onAdd && (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={S.addA11y}
          onPress={onAdd}
          className="min-h-[44px] flex-row items-center gap-1 rounded-full border border-dashed border-line-strong px-4 active:opacity-75">
          <Icon name="add" size={18} color={tokens.colors.ink.muted} />
          <Text className="text-body-sm font-semibold text-ink-muted">{S.add}</Text>
        </Pressable>
      )}
    </ScrollView>
  );
}

function StatusCard({
  device,
  elderlyName,
  busy,
  now,
  loadError,
  onRetry,
  onToggle,
}: {
  device: DeviceStatus | null;
  elderlyName: string | null;
  busy: boolean;
  now: number;
  loadError: boolean;
  onRetry: () => void;
  onToggle: () => void;
}) {
  if (!device) {
    return (
      <Card>
        {loadError ? (
          <LoadErrorBox text={S.loadError} onRetry={onRetry} />
        ) : (
          <ActivityIndicator color={tokens.colors.primary.DEFAULT} />
        )}
      </Card>
    );
  }
  const look = deviceLook(device, now);
  const lowBattery = isLowBattery(device.batteryPercent);
  return (
    <Card>
      <View className="flex-row items-start gap-3" accessible accessibilityLabel={`${device.deviceName}: ${look.label}. ${look.detail}`}>
        <View className="flex-1 gap-1">
          <View className="self-start">
            <StatusPill label={look.tone === 'ontime' ? S.onlineActive : look.label} tone={look.tone} />
          </View>
          <Text className="text-heading font-bold text-ink">{device.deviceName}</Text>
          <Text className="text-body-sm text-ink-muted">
            {S.elderlyLine(elderlyName)} · {S.lastSync(formatRelative(device.lastSyncedAt, now))}
          </Text>
        </View>
        <IconBadge icon={look.icon} tone={look.tone} />
      </View>
      <View className="flex-row gap-2">
        <StatTile icon="wifi" label={S.network} value={device.online ? device.wifiLabel : S.noNetwork} />
        <StatTile
          icon={lowBattery ? 'battery-dead-outline' : 'battery-half-outline'}
          tone={lowBattery ? 'missed' : 'ontime'}
          label={S.battery}
          value={batteryText(device.batteryPercent)}
        />
      </View>
      <View className="gap-2">
        <View className="flex-row justify-between">
          <Text className="text-body-sm text-ink-muted">{S.batteryCapacity}</Text>
          <Text className="text-body-sm font-semibold text-ink">{formatBattery(device.batteryPercent)}</Text>
        </View>
        <ProgressBar percent={device.batteryPercent ?? 0} tone={lowBattery ? 'missed' : 'primary'} />
      </View>
      <ListRow
        icon={device.openSlots.length ? 'lock-open-outline' : 'lock-closed-outline'}
        tone={device.openSlots.length ? 'late' : 'neutral'}
        title={S.doors}
        subtitle={device.openSlots.length ? S.doorsOpen(device.openSlots.join(', ')) : S.doorsClosed}
      />
      {/* With the real backend, connectivity comes from the device itself (emulator Wi-Fi toggle). */}
      {api.USE_MOCK && (
        <Button
          label={device.online ? 'Simulasi Putuskan Koneksi' : 'Simulasi Sambungkan'}
          icon={device.online ? 'cloud-offline-outline' : 'wifi-outline'}
          variant="secondary"
          loading={busy}
          onPress={onToggle}
        />
      )}
    </Card>
  );
}

function ClockCard({
  device,
  clock,
  canEdit,
  onCalibrate,
  onToggleAutoSync,
}: {
  device: DeviceStatus | null;
  clock: DeviceClock | null;
  canEdit: boolean;
  onCalibrate: () => void;
  onToggleAutoSync: (value: boolean) => void;
}) {
  const [tick, setTick] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setTick(Date.now()), CLOCK_TICK_MS);
    return () => clearInterval(timer);
  }, []);
  const accuracy =
    clock?.isAccurate == null
      ? { label: S.unknown, tone: 'neutral' as const }
      : clock.isAccurate
        ? { label: S.accurate, tone: 'ontime' as const }
        : { label: S.inaccurate, tone: 'late' as const };
  const note = pillboxClockNote(device, tick);
  return (
    <Card title={S.clockTitle} subtitle={S.clockSubtitle} right={<StatusPill label={accuracy.label} tone={accuracy.tone} />}>
      <View className="items-center gap-1 rounded-2xl bg-primary-light p-4">
        <Text className="text-caption font-semibold uppercase text-primary-dark">{S.internalClock}</Text>
        <Text className="text-time font-bold text-primary-dark" accessibilityLiveRegion="none">
          {formatPillboxClock(pillboxNow(device, tick))}
        </Text>
        <Text className="text-body-sm text-ink-muted">{clock?.timezone ?? ''}</Text>
        <Text className={`text-body-sm ${note ? 'text-late-fg' : 'text-ontime-fg'}`}>{note ?? S.synced}</Text>
      </View>
      <Button label={S.calibrate} icon="sync-outline" variant="secondary" disabled={!device?.online} onPress={onCalibrate} />
      <SwitchRow
        title={S.autoSync}
        text={canEdit ? S.autoSyncText : S.ownerOnly}
        value={clock?.autoSyncTimezone ?? false}
        disabled={!canEdit || !clock}
        onChange={onToggleAutoSync}
      />
      <View className="flex-row gap-2 rounded-2xl bg-info-soft p-3">
        <Icon name="shield-checkmark-outline" size={20} color={tokens.colors.info.fg} />
        <Text className="flex-1 text-body-sm text-info-fg">{S.rtcNote}</Text>
      </View>
    </Card>
  );
}

function SimulatorCard({
  slots,
  slotId,
  onSelectSlot,
  minutesLate,
  onChangeMinutesLate,
  busyType,
  onSimulate,
  seeding,
  onSeed,
}: {
  slots: Slot[];
  slotId: SlotId | null;
  onSelectSlot: (id: SlotId) => void;
  minutesLate: number;
  onChangeMinutesLate: (value: number) => void;
  busyType: DoseEventType | null;
  onSimulate: (type: DoseEventType) => void;
  seeding: boolean;
  onSeed: () => void;
}) {
  const disabled = slotId === null || busyType !== null;
  return (
    <Card title="Alat Uji (Simulasi IoT)" subtitle="Kirim kejadian seolah-olah dari Pillbox" icon="flask-outline" tone="info">
      <View className="gap-2">
        <Text className="text-body font-semibold text-ink">Bilik</Text>
        <View className="flex-row flex-wrap gap-2">
          {SLOT_IDS.map((id) => (
            <Chip
              key={id}
              label={id}
              selected={slotId === id}
              disabled={!isSlotActive(slots.find((s) => s.id === id))}
              onPress={() => onSelectSlot(id)}
            />
          ))}
        </View>
        {slotId === null && <Text className="text-body-sm text-missed-fg">Tidak ada bilik aktif yang tersimpan.</Text>}
      </View>

      <View className="min-h-[56px] flex-row items-center justify-between rounded-2xl bg-canvas px-3">
        <Text className="text-body font-semibold text-ink">Menit terlambat</Text>
        <View className="flex-row items-center gap-2">
          <Button
            label="−5"
            accessibilityLabel="Kurangi 5 menit"
            variant="secondary"
            size="sm"
            disabled={minutesLate <= 5}
            onPress={() => onChangeMinutesLate(minutesLate - 5)}
          />
          <Text className="w-12 text-center text-title font-bold text-ink" accessibilityLabel={`${minutesLate} menit`}>
            {minutesLate}
          </Text>
          <Button
            label="+5"
            accessibilityLabel="Tambah 5 menit"
            variant="secondary"
            size="sm"
            disabled={minutesLate >= 180}
            onPress={() => onChangeMinutesLate(minutesLate + 5)}
          />
        </View>
      </View>

      <View className="gap-2">
        <Button
          label="Diminum Tepat Waktu"
          icon="checkmark-circle-outline"
          variant="success"
          disabled={disabled}
          loading={busyType === 'on_time'}
          onPress={() => onSimulate('on_time')}
        />
        <Button
          label={`Diminum Terlambat (${minutesLate} menit)`}
          icon="time-outline"
          variant="warning"
          disabled={disabled}
          loading={busyType === 'late'}
          onPress={() => onSimulate('late')}
        />
        <Button
          label="Dosis Terlewat"
          icon="alert-circle-outline"
          variant="danger"
          disabled={disabled}
          loading={busyType === 'missed'}
          onPress={() => onSimulate('missed')}
        />
        {api.USE_MOCK && (
          <Button label="Tambah 45 Riwayat Contoh" icon="layers-outline" variant="ghost" loading={seeding} onPress={onSeed} />
        )}
      </View>
    </Card>
  );
}

export function DeviceTab({
  device,
  pillboxes,
  activeId,
  elderlyName,
  clock,
  canEditDevice,
  connectionBusy,
  now,
  loadError,
  onRetry,
  onToggleConnection,
  refreshing,
  onRefresh,
  onSelectPillbox,
  onAdd,
  onCalibrate,
  onToggleAutoSync,
  onOpenSchedule,
  pillboxList,
  simulator,
}: {
  device: DeviceStatus | null;
  pillboxes: Pillbox[];
  activeId: string | null;
  elderlyName: string | null;
  clock: DeviceClock | null;
  /** OWNER / ADMIN of the active pillbox's elderly profile. */
  canEditDevice: boolean;
  connectionBusy: boolean;
  now: number;
  loadError: boolean;
  onRetry: () => void;
  onToggleConnection: () => void;
  refreshing: boolean;
  onRefresh: () => void;
  onSelectPillbox: (pillbox: Pillbox) => void;
  /** Omitted in mock mode (no pairing). */
  onAdd?: () => void;
  onCalibrate: () => void;
  onToggleAutoSync: (value: boolean) => void;
  onOpenSchedule: () => void;
  /** "Pillbox Anda" list (backend mode). */
  pillboxList: ReactNode;
  simulator: Parameters<typeof SimulatorCard>[0];
}) {
  const online = pillboxes.filter((p) => p.online).length;
  return (
    <ScrollView
      contentContainerClassName="gap-4 px-4 pb-8 pt-4"
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          colors={[tokens.colors.primary.DEFAULT]}
          tintColor={tokens.colors.primary.DEFAULT}
        />
      }>
      <View className="gap-2">
        <ScreenHeader title={S.title} subtitle={api.USE_MOCK ? Strings.shell.mockMode : S.subtitle} />
        {pillboxes.length > 0 && (
          <View className="self-start">
            <StatusPill label={S.connectedCount(online)} tone={online > 0 ? 'ontime' : 'neutral'} />
          </View>
        )}
      </View>
      <PillboxChips pillboxes={pillboxes} activeId={activeId} onSelect={onSelectPillbox} onAdd={onAdd} />
      <StatusCard
        device={device}
        elderlyName={elderlyName}
        busy={connectionBusy}
        now={now}
        loadError={loadError}
        onRetry={onRetry}
        onToggle={onToggleConnection}
      />
      {onAdd && (
        <Card>
          <ListRow icon="qr-code-outline" title={S.connectTitle} subtitle={S.connectText} onPress={onAdd} />
        </Card>
      )}
      <ClockCard device={device} clock={clock} canEdit={canEditDevice} onCalibrate={onCalibrate} onToggleAutoSync={onToggleAutoSync} />
      <Card>
        <ListRow
          icon="options-outline"
          title={S.manageTitle}
          subtitle={S.manageText}
          onPress={onOpenSchedule}
          right={<Text className="text-body-sm font-bold text-primary">{S.manageAction}</Text>}
        />
      </Card>
      {pillboxList}
      {/* Mock only: with the real backend, events come from the smart device emulator. */}
      {api.USE_MOCK && <SimulatorCard {...simulator} />}
    </ScrollView>
  );
}
