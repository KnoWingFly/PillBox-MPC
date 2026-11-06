import { memo, type ReactNode } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import type { DashboardInsights } from '@/hooks/use-dashboard-insights';
import * as tokens from '@/theme/tokens';
import * as api from '@root/lib/api';
import type { Pillbox } from '@root/lib/devices';
import type { TodayDose, WeekMissed } from '@root/lib/insights';
import type { AdherenceSummary, DeviceStatus, SlotId } from '@root/lib/types';

import { AlarmButton, type AlarmControl } from './alarm-button';
import { Avatar, ProgressRing, QuickAction, StatTile, TextLink } from './blocks';
import {
  adherenceBand,
  ageInYears,
  COLUMNS,
  columnIndex,
  deviceLook,
  doseLook,
  firstName,
  formatPillboxDate,
  formatBattery,
  isLowBattery,
} from './helpers';
import type { TabKey } from './tab-bar';
import { Button, Card, Icon, IconBadge, LoadErrorBox, StatusPill, TONE } from './ui';

const S = Strings.home;

function ElderlyCard({
  name,
  age,
  activeCount,
  online,
  onPress,
}: {
  name: string;
  age: number | null;
  activeCount: number;
  online: boolean;
  onPress: () => void;
}) {
  const title = age === null ? name : `${name} (${Strings.shell.ageYears(age)})`;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={S.elderlyA11y(title)}
      onPress={onPress}
      className="flex-row items-center gap-3 rounded-3xl bg-primary-light p-4 active:opacity-80">
      <Avatar name={name} online={online} />
      <View className="flex-1">
        <Text className="text-body font-bold text-ink" numberOfLines={1}>
          {title}
        </Text>
        <Text className="text-body-sm font-semibold text-primary-dark">{S.elderlyActive(activeCount)}</Text>
      </View>
      <Icon name="chevron-expand" size={20} color={tokens.colors.primary.dark} />
    </Pressable>
  );
}

function AdherenceCard({ summary }: { summary: AdherenceSummary | null }) {
  const percent = summary?.adherencePercent ?? null;
  const band = adherenceBand(percent);
  const taken = summary ? summary.onTimeDoses + summary.lateDoses : 0;
  return (
    <Card>
      <View>
        <Text className="text-caption font-semibold uppercase text-ink-muted">{S.adherenceEyebrow}</Text>
        <Text className="text-title font-bold text-ink" accessibilityRole="header">
          {S.adherenceTitle}
        </Text>
      </View>
      <View className="flex-row items-center gap-4">
        <View accessible accessibilityLabel={S.adherenceA11y(percent, band.label)}>
          <ProgressRing percent={percent} tone={band.tone}>
            <Text className="text-heading font-bold text-ink">{percent === null ? '–' : `${percent}%`}</Text>
            <Text className={`text-center text-caption font-semibold ${TONE[band.tone].fg}`}>
              {band.label}
            </Text>
          </ProgressRing>
        </View>
        <View className="flex-1 gap-2">
          <StatTile
            icon="time-outline"
            tone="primary"
            label={S.avgDelay}
            value={summary?.averageDelayMinutes == null ? '–' : S.minutes(summary.averageDelayMinutes)}
          />
          <Text className="text-body-sm text-ink-muted">
            {summary && summary.totalDoses > 0 ? S.takenOf(taken, summary.totalDoses, summary.periodLabel) : S.noDoses}
          </Text>
        </View>
      </View>
    </Card>
  );
}

const DoseRow = memo(function DoseRow({ dose }: { dose: TodayDose }) {
  const look = doseLook(dose);
  const column = COLUMNS[columnIndex(dose.slotId)];
  const missed = dose.status === 'MISSED';
  const slot = `Slot ${dose.slotId} · ${api.getSlotRowLabel(dose.slotId)}`;
  return (
    <View
      className={`flex-row items-center gap-3 rounded-2xl p-3 ${missed ? 'bg-missed-soft' : 'bg-canvas'}`}
      accessible
      accessibilityLabel={`${dose.scheduledTime} ${column.label}. ${slot}. ${look.label}`}>
      <IconBadge icon={column.icon} tone={missed ? 'missed' : 'primary'} size="sm" />
      <View className="flex-1 gap-1">
        <View className="flex-row flex-wrap items-center justify-between gap-2">
          <Text className="text-body font-bold text-ink">
            {dose.scheduledTime} <Text className="text-body-sm font-medium text-ink-muted">· {column.label}</Text>
          </Text>
          <StatusPill label={look.label} tone={look.tone} />
        </View>
        <Text className="text-body-sm text-ink-muted">{slot}</Text>
      </View>
    </View>
  );
});

function MissedWarning({
  dose,
  elderlyName,
  remindBusy,
  alarm,
  onCall,
  onRemind,
}: {
  dose: TodayDose;
  elderlyName: string;
  remindBusy: boolean;
  alarm: AlarmControl;
  /** Omitted when the elderly profile has no phone number: nothing is dialed then. */
  onCall?: () => void;
  onRemind: (slotId: SlotId) => void;
}) {
  const period = COLUMNS[columnIndex(dose.slotId)].label;
  return (
    <View className="gap-3 rounded-2xl border border-missed-border bg-missed-soft p-4" accessibilityRole="alert">
      <View className="flex-row items-start gap-2">
        <Icon name="warning-outline" size={22} color={tokens.colors.missed.fg} />
        <View className="flex-1 gap-1">
          <Text className="text-body font-bold text-missed-fg">{S.warningTitle(period)}</Text>
          <Text className="text-body-sm text-missed-fg">{S.warningText(dose.slotId, elderlyName)}</Text>
        </View>
      </View>
      <View className="gap-2">
        {onCall && <Button label={S.callNow} icon="call-outline" variant="danger" size="sm" onPress={onCall} />}
        <AlarmButton
            label={S.sendReminder}
            icon="alarm-outline"
            variant="danger-soft"
            size="sm"
            starting={remindBusy}
            onStart={() => onRemind(dose.slotId)}
            alarm={alarm}
          />
      </View>
    </View>
  );
}

function TodayCard({
  doses,
  error,
  dateLabel,
  onRetry,
  onOpenSchedule,
  warning,
}: {
  doses: TodayDose[] | null;
  error: boolean;
  dateLabel: string;
  onRetry: () => void;
  onOpenSchedule: () => void;
  warning: ReactNode;
}) {
  return (
    <Card title={S.todayTitle} subtitle={dateLabel} right={<TextLink label={S.fullSchedule} onPress={onOpenSchedule} />}>
      {doses === null ? (
        error ? (
          <LoadErrorBox text={S.todayError} onRetry={onRetry} />
        ) : (
          <ActivityIndicator color={tokens.colors.primary.DEFAULT} />
        )
      ) : doses.length === 0 ? (
        <Text className="text-body text-ink-muted">{S.todayEmpty}</Text>
      ) : (
        <View className="gap-2">
          {doses.map((d) => (
            <DoseRow key={d.key} dose={d} />
          ))}
        </View>
      )}
      {warning}
    </Card>
  );
}

const BAR_MAX_HEIGHT = 72;
const BAR_MIN_HEIGHT = 8;

function WeekCard({ week }: { week: WeekMissed | null }) {
  if (!week) return null;
  const total = week.days.reduce((sum, d) => sum + d.missed, 0);
  const max = Math.max(1, ...week.days.map((d) => d.missed));
  const trend =
    week.previousTotal === null
      ? null
      : total < week.previousTotal
        ? { label: S.trendDown, tone: 'ontime' as const }
        : total > week.previousTotal
          ? { label: S.trendUp, tone: 'missed' as const }
          : { label: S.trendFlat, tone: 'neutral' as const };
  return (
    <Card title={S.weekTitle} subtitle={S.weekSubtitle} right={trend && <StatusPill label={trend.label} tone={trend.tone} />}>
      <View className="flex-row items-end justify-between gap-2">
        {week.days.map((d, i) => {
          const today = i === week.todayIndex;
          const filled = d.missed > 0;
          return (
            <View key={d.date} className="flex-1 items-center gap-1" accessible accessibilityLabel={S.weekA11y(S.weekDays[i], d.missed)}>
              <Text className={`text-caption font-semibold ${filled ? 'text-missed-fg' : 'text-ink-muted'}`}>{d.missed}</Text>
              <View
                className={`w-full rounded-lg ${filled ? 'bg-missed-solid' : 'bg-canvas'}`}
                style={{ height: filled ? Math.max(BAR_MIN_HEIGHT, (d.missed / max) * BAR_MAX_HEIGHT) : BAR_MIN_HEIGHT }}
              />
              <Text className={`text-caption ${today ? 'font-bold text-primary' : 'text-ink-muted'}`}>{S.weekDays[i]}</Text>
            </View>
          );
        })}
      </View>
    </Card>
  );
}

function PillboxCard({
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
      <Card>
        {loadError ? <LoadErrorBox text={S.pillboxLoadError} onRetry={onRetry} /> : <ActivityIndicator color={tokens.colors.primary.DEFAULT} />}
      </Card>
    );
  }
  const look = deviceLook(device, now);
  const lowBattery = isLowBattery(device.batteryPercent);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={S.pillboxA11y(device.deviceName, look.label, formatBattery(device.batteryPercent))}
      onPress={onOpen}
      className="flex-row items-center gap-3 rounded-3xl border border-line bg-surface p-4 active:opacity-80"
      style={{ boxShadow: tokens.shadow.card }}>
      <IconBadge icon="cube-outline" tone="primary" size="lg" />
      <View className="flex-1 gap-1">
        <View className="flex-row flex-wrap items-center gap-2">
          <Text className="text-body font-bold text-ink">{device.deviceName}</Text>
          <StatusPill label={device.online ? Strings.shell.online : Strings.shell.offline} tone={look.tone} />
        </View>
        <View className="flex-row items-center gap-3">
          <View className="flex-row items-center gap-1">
            <Icon
              name={lowBattery ? 'battery-dead-outline' : 'battery-half-outline'}
              size={16}
              color={lowBattery ? tokens.colors.missed.fg : tokens.colors.ink.muted}
            />
            <Text className={`text-body-sm ${lowBattery ? 'text-missed-fg' : 'text-ink-muted'}`}>{formatBattery(device.batteryPercent)}</Text>
          </View>
          <View className="flex-1 flex-row items-center gap-1">
            <Icon name={device.online ? 'wifi' : 'cloud-offline-outline'} size={16} color={tokens.colors.ink.muted} />
            <Text className="flex-1 text-body-sm text-ink-muted" numberOfLines={1}>
              {device.online ? device.wifiLabel : Strings.device.noNetwork}
            </Text>
          </View>
        </View>
      </View>
      <Icon name="options-outline" size={22} color={tokens.colors.ink.muted} />
    </Pressable>
  );
}

export function HomeTab({
  now,
  pillboxNow,
  userName,
  pillbox,
  device,
  deviceLoadError,
  onRetryDevice,
  adherence,
  insights,
  unreadCount,
  remindBusy,
  alarm,
  refreshing,
  onRefresh,
  onOpenTab,
  onAddElderly,
  onCall,
  onRemind,
}: {
  now: number;
  /** Time on the pillbox clock: the day follows it. */
  pillboxNow: number;
  userName: string | null;
  pillbox: Pillbox | null;
  device: DeviceStatus | null;
  deviceLoadError: boolean;
  onRetryDevice: () => void;
  adherence: AdherenceSummary | null;
  insights: Pick<DashboardInsights, 'todayDoses' | 'dosesError' | 'week' | 'elderly' | 'refreshDoses'>;
  unreadCount: number;
  remindBusy: boolean;
  alarm: AlarmControl;
  refreshing: boolean;
  onRefresh: () => void;
  onOpenTab: (tab: TabKey) => void;
  /** Omitted when profiles cannot be created (mock mode). */
  onAddElderly?: () => void;
  /** Omitted when the elderly profile has no phone number. */
  onCall?: () => void;
  onRemind: (slotId: SlotId) => void;
}) {
  const elderlyName = insights.elderly?.fullName ?? pillbox?.elderlyName ?? Strings.shell.elderlyFallback;
  const doses = insights.todayDoses;
  const lastMissed = doses ? [...doses].reverse().find((d) => d.status === 'MISSED') : undefined;
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
      <View>
        <Text className="text-display font-bold tracking-tight text-ink" accessibilityRole="header">
          {S.greeting(firstName(userName))}
        </Text>
        <Text className="text-body-sm text-ink-muted">{api.USE_MOCK ? Strings.shell.mockMode : S.subtitle}</Text>
      </View>
      <ElderlyCard
        name={elderlyName}
        age={ageInYears(insights.elderly?.birthDate ?? null, pillboxNow)}
        activeCount={doses?.length ?? 0}
        online={device?.online ?? false}
        onPress={() => onOpenTab('device')}
      />
      <AdherenceCard summary={adherence} />
      <TodayCard
        doses={doses}
        error={insights.dosesError}
        dateLabel={formatPillboxDate(pillboxNow)}
        onRetry={insights.refreshDoses}
        onOpenSchedule={() => onOpenTab('schedule')}
        warning={
          lastMissed && (
            <MissedWarning
              dose={lastMissed}
              elderlyName={elderlyName}
              remindBusy={remindBusy}
              alarm={alarm}
              onCall={onCall}
              onRemind={onRemind}
            />
          )
        }
      />
      <WeekCard week={insights.week} />
      <PillboxCard device={device} now={now} loadError={deviceLoadError} onRetry={onRetryDevice} onOpen={() => onOpenTab('device')} />
      <View className="gap-2">
        <Text className="text-title font-bold text-ink" accessibilityRole="header">
          {S.quickTitle}
        </Text>
        <View className="flex-row">
          <QuickAction icon="grid-outline" label={S.quick.schedule} onPress={() => onOpenTab('schedule')} />
          <QuickAction icon="cube-outline" label={S.quick.device} onPress={() => onOpenTab('device')} />
          <QuickAction
            icon="notifications-outline"
            label={S.quick.notifications}
            dot={unreadCount > 0}
            onPress={() => onOpenTab('notifications')}
          />
          {onAddElderly && <QuickAction icon="person-add-outline" label={S.quick.addElderly} onPress={onAddElderly} />}
        </View>
      </View>
    </ScrollView>
  );
}
