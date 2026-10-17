import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';

import * as tokens from '@/theme/tokens';
import * as api from '@root/lib/api';
import { formatJakartaTimestamp, SCHEDULE_TIMEZONE_LABEL } from '@root/lib/schedule-time';
import type { AdherenceSummary, AppNotification, DeviceStatus, Slot } from '@root/lib/types';

import {
  deviceLook,
  formatDuration,
  formatJakartaDate,
  formatRelative,
  greeting,
  LOW_BATTERY_PERCENT,
  nextDose,
  notificationLook,
  slotTitle,
} from './helpers';
import type { TabKey } from './tab-bar';
import { Button, Card, Icon, IconBadge, LoadErrorBox, ScreenHeader, StatusPill } from './ui';

function AdherenceHero({ summary }: { summary: AdherenceSummary | null }) {
  const total = summary?.totalDoses ?? 0;
  const segments = summary
    ? [
        { key: 'ontime', count: summary.onTimeDoses, color: tokens.colors.ontime.border, label: 'Tepat waktu' },
        { key: 'late', count: summary.lateDoses, color: tokens.colors.late.border, label: 'Terlambat' },
        { key: 'missed', count: summary.missedDoses, color: tokens.colors.missed.border, label: 'Terlewat' },
      ]
    : [];

  return (
    <View
      className="gap-4 rounded-3xl bg-primary p-5"
      style={{ boxShadow: tokens.shadow.raised }}
      accessible
      accessibilityLabel={
        summary && summary.adherencePercent !== null
          ? `Kepatuhan ${summary.adherencePercent} persen dari ${total} dosis. Tepat waktu ${summary.onTimeDoses}, terlambat ${summary.lateDoses}, terlewat ${summary.missedDoses}.`
          : 'Kepatuhan belum ada data.'
      }>
      <View className="flex-row items-start justify-between">
        <View className="gap-1">
          <Text className="text-body-sm font-semibold text-white">Kepatuhan minum obat</Text>
          <Text className="text-[44px] font-bold leading-[52px] tracking-tight text-white">
            {summary?.adherencePercent == null ? '–' : `${summary.adherencePercent}%`}
          </Text>
          <Text className="text-body-sm text-white">
            {total > 0
              ? `dari ${total} dosis tercatat${summary?.periodLabel ? ` · ${summary.periodLabel}` : ''}`
              : summary
                ? `Belum ada dosis tercatat${summary.periodLabel ? ` · ${summary.periodLabel}` : ''}`
                : 'Data kepatuhan belum tersedia'}
          </Text>
        </View>
        <View className="items-end gap-1 rounded-2xl bg-primary-pressed px-4 py-3">
          <Text className="text-caption text-white">Rata-rata telat</Text>
          <Text className="text-title font-bold text-white">
            {summary?.averageDelayMinutes == null ? '–' : `${summary.averageDelayMinutes} mnt`}
          </Text>
        </View>
      </View>

      {/* Stacked bar: share of on-time / late / missed doses. */}
      <View className="h-3 flex-row overflow-hidden rounded-full bg-primary-pressed">
        {total > 0 &&
          segments.map((s) =>
            s.count > 0 ? <View key={s.key} style={{ flex: s.count, backgroundColor: s.color }} /> : null,
          )}
      </View>
      <View className="flex-row flex-wrap gap-x-4 gap-y-1">
        {segments.map((s) => (
          <View key={s.key} className="flex-row items-center gap-1.5">
            <View className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: s.color }} />
            <Text className="text-body-sm text-white">
              {s.label} {s.count}
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}

function NextDoseCard({ slots, now, onOpen }: { slots: Slot[]; now: number; onOpen: () => void }) {
  const next = nextDose(slots, now);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={
        next
          ? `Dosis berikutnya ${next.tomorrow ? 'besok' : 'hari ini'} pukul ${api.formatTime(next.slot.timeMinutes)}, slot ${next.slot.id}. Buka jadwal.`
          : 'Belum ada jadwal aktif. Buka jadwal.'
      }
      onPress={onOpen}
      className="flex-row items-center gap-4 rounded-3xl border border-line bg-surface p-5 active:opacity-80"
      style={{ boxShadow: tokens.shadow.card }}>
      <IconBadge icon="alarm-outline" tone="primary" size="lg" />
      <View className="flex-1 gap-0.5">
        <Text className="text-body-sm font-semibold text-ink-muted">Dosis berikutnya</Text>
        {next ? (
          <>
            <Text className="text-heading font-bold text-ink">
              {api.formatTime(next.slot.timeMinutes)}{' '}
              <Text className="text-body font-semibold text-ink-muted">
                {SCHEDULE_TIMEZONE_LABEL}
                {next.tomorrow ? ' · besok' : ''}
              </Text>
            </Text>
            <Text className="text-body-sm text-ink-muted">
              Slot {next.slot.id} · {slotTitle(next.slot.id)} · dalam {formatDuration(next.inMinutes)}
            </Text>
          </>
        ) : (
          <Text className="text-body text-ink">Belum ada jadwal aktif</Text>
        )}
      </View>
      <Icon name="chevron-forward" size={20} color={tokens.colors.ink.muted} />
    </Pressable>
  );
}

function DeviceSummary({
  device,
  now,
  loadError,
  onRetry,
  onOpen,
}: {
  device: DeviceStatus | null;
  now: number;
  loadError: boolean;
  onRetry: () => void;
  onOpen: () => void;
}) {
  if (!device) {
    return (
      <Card title="Pillbox" icon="hardware-chip-outline">
        {loadError ? (
          <LoadErrorBox text="Gagal memuat status Pillbox." onRetry={onRetry} />
        ) : (
          <ActivityIndicator color={tokens.colors.primary.DEFAULT} accessibilityLabel="Memuat status perangkat" />
        )}
      </Card>
    );
  }
  const look = deviceLook(device, now);
  const lowBattery = device.batteryPercent <= LOW_BATTERY_PERCENT;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${device.deviceName}: ${look.label}. Baterai ${device.batteryPercent} persen. Sinkron ${formatRelative(device.lastSyncedAt, now)}. Buka perangkat.`}
      onPress={onOpen}
      className="gap-4 rounded-3xl border border-line bg-surface p-5 active:opacity-80"
      style={{ boxShadow: tokens.shadow.card }}>
      <View className="flex-row items-center gap-3">
        <IconBadge icon="hardware-chip-outline" tone={look.tone} />
        <View className="flex-1">
          <Text className="text-title font-bold text-ink">{device.deviceName}</Text>
          <Text className="text-body-sm text-ink-muted">Sinkron {formatRelative(device.lastSyncedAt, now)}</Text>
        </View>
        <StatusPill label={look.label} tone={look.tone} />
      </View>
      <View className="flex-row gap-3">
        <View className={`flex-1 flex-row items-center gap-2 rounded-2xl p-3 ${lowBattery ? 'bg-missed-soft' : 'bg-battery-soft'}`}>
          <Icon
            name={lowBattery ? 'battery-dead' : 'battery-half'}
            size={20}
            color={lowBattery ? tokens.colors.missed.fg : tokens.colors.battery.fg}
          />
          <Text className={`text-body font-semibold ${lowBattery ? 'text-missed-fg' : 'text-battery-fg'}`}>
            {device.batteryPercent}%{lowBattery ? ' · Lemah' : ''}
          </Text>
        </View>
        <View className="flex-1 flex-row items-center gap-2 rounded-2xl bg-canvas p-3">
          <Icon name={device.online ? 'wifi' : 'cloud-offline-outline'} size={20} color={tokens.colors.ink.muted} />
          <Text className="flex-1 text-body font-semibold text-ink" numberOfLines={1}>
            {device.online ? device.wifiLabel : 'Tidak terhubung'}
          </Text>
        </View>
      </View>
    </Pressable>
  );
}

function RecentNotifications({
  items,
  now,
  onOpen,
}: {
  items: AppNotification[];
  now: number;
  onOpen: () => void;
}) {
  return (
    <Card
      title="Notifikasi terbaru"
      icon="notifications-outline"
      right={<Button label="Semua" variant="ghost" size="sm" onPress={onOpen} accessibilityLabel="Lihat semua notifikasi" />}>
      {items.length === 0 ? (
        <Text className="text-body text-ink-muted">Belum ada notifikasi.</Text>
      ) : (
        <View className="gap-1">
          {items.map((n) => {
            const look = notificationLook(n);
            return (
              <Pressable
                key={n.id}
                accessibilityRole="button"
                accessibilityLabel={`${look.label}. ${n.title}. ${formatRelative(n.createdAt, now)}. Buka notifikasi.`}
                onPress={onOpen}
                className="min-h-[56px] flex-row items-center gap-3 rounded-2xl py-2 active:opacity-75">
                <IconBadge icon={look.icon} tone={look.tone} size="sm" />
                <View className="flex-1">
                  <Text className={`text-body text-ink ${n.read ? 'font-medium' : 'font-bold'}`} numberOfLines={1}>
                    {n.title}
                  </Text>
                  <Text className="text-body-sm text-ink-muted" numberOfLines={1}>
                    {n.slotId ? `Slot ${n.slotId} · ` : ''}
                    {formatJakartaTimestamp(n.createdAt, now)} · {formatRelative(n.createdAt, now)}
                  </Text>
                </View>
                {!n.read && <View className="h-2.5 w-2.5 rounded-full bg-missed-solid" />}
              </Pressable>
            );
          })}
        </View>
      )}
    </Card>
  );
}

export function HomeTab({
  now,
  pillboxNow,
  device,
  deviceLoadError,
  onRetryDevice,
  adherence,
  savedSlots,
  recent,
  refreshing,
  onRefresh,
  onOpenTab,
}: {
  now: number;
  /** Time on the pillbox clock: the day and the next dose follow it. */
  pillboxNow: number;
  device: DeviceStatus | null;
  deviceLoadError: boolean;
  onRetryDevice: () => void;
  adherence: AdherenceSummary | null;
  savedSlots: Slot[];
  recent: AppNotification[];
  refreshing: boolean;
  onRefresh: () => void;
  onOpenTab: (tab: TabKey) => void;
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
        eyebrow={formatJakartaDate(pillboxNow)}
        title={greeting(pillboxNow)}
        subtitle={api.USE_MOCK ? 'Mode uji · data tiruan' : 'Pantau obat lansia dari sini'}
      />
      <AdherenceHero summary={adherence} />
      <NextDoseCard slots={savedSlots} now={pillboxNow} onOpen={() => onOpenTab('schedule')} />
      <DeviceSummary
        device={device}
        now={now}
        loadError={deviceLoadError}
        onRetry={onRetryDevice}
        onOpen={() => onOpenTab('device')}
      />
      <RecentNotifications items={recent} now={now} onOpen={() => onOpenTab('notifications')} />
    </ScrollView>
  );
}
