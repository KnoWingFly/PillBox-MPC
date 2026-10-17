import { ActivityIndicator, RefreshControl, ScrollView, Text, View } from 'react-native';

import * as tokens from '@/theme/tokens';
import * as api from '@root/lib/api';
import { formatJakartaTimestamp } from '@root/lib/schedule-time';
import { SLOT_IDS, type DeviceStatus, type DoseEventType, type Slot, type SlotId } from '@root/lib/types';

import { deviceLook, formatRelative, isSlotActive, LOW_BATTERY_PERCENT, pillboxClockNote, pillboxNow } from './helpers';
import { Button, Card, Chip, Divider, IconBadge, InfoRow, LoadErrorBox, ScreenHeader, StatusPill } from './ui';

function ConnectionCard({
  device,
  busy,
  now,
  loadError,
  onRetry,
  onToggle,
}: {
  device: DeviceStatus | null;
  busy: boolean;
  now: number;
  loadError: boolean;
  onRetry: () => void;
  onToggle: () => void;
}) {
  if (!device) {
    return (
      <Card title="Status Pillbox" icon="hardware-chip-outline">
        {loadError ? (
          <LoadErrorBox text="Gagal memuat status Pillbox. Periksa koneksi lalu coba lagi." onRetry={onRetry} />
        ) : (
          <ActivityIndicator color={tokens.colors.primary.DEFAULT} accessibilityLabel="Memuat status perangkat" />
        )}
      </Card>
    );
  }
  const look = deviceLook(device, now);
  const lowBattery = device.batteryPercent <= LOW_BATTERY_PERCENT;
  const lastSync = `${formatJakartaTimestamp(device.lastSyncedAt, now)} WIB · ${formatRelative(device.lastSyncedAt, now)}`;
  const clockNote = pillboxClockNote(device, now);
  const pillboxTime = `${formatJakartaTimestamp(pillboxNow(device, now), now)} WIB${clockNote ? ` · ${clockNote}` : ''}`;

  return (
    <Card>
      <View
        className="items-center gap-3 py-2"
        accessible
        accessibilityRole="summary"
        accessibilityLabel={`${device.deviceName}: ${look.label}. ${look.detail}`}>
        <IconBadge icon={look.icon} tone={look.tone} size="lg" />
        <View className="items-center gap-1">
          <Text className="text-heading font-bold text-ink">{device.deviceName}</Text>
          <StatusPill label={look.label} tone={look.tone} />
        </View>
        <Text className="text-center text-body-sm text-ink-muted">{look.detail}</Text>
      </View>
      <Divider />
      <View>
        <InfoRow icon="sync-outline" label="Sinkron" value={lastSync} valueClassName={look.tone === 'late' ? 'text-late-fg' : 'text-ink'} />
        {device.clock && (
          <InfoRow icon="time-outline" label="Jam Pillbox" value={pillboxTime} valueClassName={clockNote ? 'text-late-fg' : 'text-ink'} />
        )}
        <InfoRow
          icon={lowBattery ? 'battery-dead-outline' : 'battery-half-outline'}
          label="Baterai"
          value={lowBattery ? `${device.batteryPercent}% · Segera isi daya` : `${device.batteryPercent}%`}
          valueClassName={lowBattery ? 'text-missed-fg' : 'text-battery-fg'}
        />
        <InfoRow icon="wifi-outline" label="Wi-Fi" value={device.online ? device.wifiLabel : 'Tidak terhubung'} />
        <InfoRow
          icon={device.openSlots.length ? 'lock-open-outline' : 'lock-closed-outline'}
          label="Pintu bilik"
          value={device.openSlots.length ? `Terbuka: ${device.openSlots.join(', ')}` : 'Semua tertutup'}
          valueClassName={device.openSlots.length ? 'text-late-fg' : 'text-ink'}
        />
      </View>
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
  connectionBusy,
  now,
  loadError,
  onRetry,
  onToggleConnection,
  refreshing,
  onRefresh,
  simulator,
}: {
  device: DeviceStatus | null;
  connectionBusy: boolean;
  now: number;
  loadError: boolean;
  onRetry: () => void;
  onToggleConnection: () => void;
  refreshing: boolean;
  onRefresh: () => void;
  simulator: Parameters<typeof SimulatorCard>[0];
}) {
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
      <ScreenHeader
        title="Perangkat"
        subtitle={api.USE_MOCK ? 'Koneksi, baterai, dan alat uji Pillbox' : 'Koneksi, baterai, dan pintu bilik Pillbox'}
      />
      <ConnectionCard
        device={device}
        busy={connectionBusy}
        now={now}
        loadError={loadError}
        onRetry={onRetry}
        onToggle={onToggleConnection}
      />
      {/* Mock only: with the real backend, events come from the smart device emulator. */}
      {api.USE_MOCK && <SimulatorCard {...simulator} />}
    </ScrollView>
  );
}
