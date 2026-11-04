import { ActivityIndicator, Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import { useConfigSync, type ConfigSyncState } from '@/hooks/use-config-sync';
import * as tokens from '@/theme/tokens';
import * as api from '@root/lib/api';
import type { DeviceStatus, Slot } from '@root/lib/types';

import { SuccessSheet } from '../ui/success-sheet';
import { formatBattery, isSlotActive } from './helpers';
import { Icon, IconBadge, StatusPill } from './ui';

const S = Strings.schedule;

/** One synced slot: number, "Slot A1 • Pagi", time and meal row. At most 8, so no list virtualization. */
function SyncedSlotRow({ slot, index, timezoneLabel }: { slot: Slot; index: number; timezoneLabel: string }) {
  return (
    <View className="flex-row items-center gap-3 rounded-2xl bg-surface p-3">
      <View className="h-9 w-9 items-center justify-center rounded-full bg-primary-light">
        <Text className="text-body-sm font-bold text-primary-dark">{index + 1}</Text>
      </View>
      <View className="flex-1">
        <Text className="text-body font-bold text-ink">{S.syncedSlot(slot.id, api.getSlotColumnLabel(slot.id))}</Text>
        <Text className="text-body-sm text-ink-muted">
          {S.syncedSlotLine(api.formatTime(slot.timeMinutes), timezoneLabel, api.getSlotRowLabel(slot.id))}
        </Text>
      </View>
    </View>
  );
}

type Props = {
  /** The saved schedule; null = hidden. */
  slots: Slot[] | null;
  device: DeviceStatus | null;
  /** Pillbox name, already resolved by the caller (status, else the list, else the default). */
  deviceName: string;
  timezoneLabel: string;
  elderlyName: string | null;
  onHome: () => void;
  onClose: () => void;
};

const COPY: Record<ConfigSyncState, { title: string; status: string }> = {
  checking: { title: S.sendingTitle, status: S.sending },
  applied: { title: S.syncedTitle, status: S.connected },
  waiting: { title: S.pendingTitle, status: S.pendingStatus },
};

/**
 * After a schedule save: "Jadwal Obat Berhasil Disinkronkan!" only once the pillbox reports the new
 * config version as applied. Until then it says the schedule was sent, and after the timeout (e.g.
 * the pillbox is offline) that it waits for the pillbox. Mounted per save, so the check starts over.
 */
export function ScheduleSyncedSheet(props: Props) {
  if (props.slots === null) return null;
  return <SyncedSheet {...props} slots={props.slots} />;
}

function SyncedSheet({ slots, device, deviceName, timezoneLabel, elderlyName, onHome, onClose }: Props & { slots: Slot[] }) {
  const sync = useConfigSync();
  const active = slots.filter(isSlotActive);
  const minTolerance = active.length ? Math.min(...active.map((s) => s.toleranceMinutes)) : null;
  const copy = COPY[sync];
  const message =
    sync === 'applied' ? S.syncedText(active.length, deviceName, elderlyName) : sync === 'checking' ? S.sendingText(deviceName) : S.pendingText(deviceName);

  return (
    <SuccessSheet
      visible
      tone={sync === 'applied' ? 'done' : 'pending'}
      title={copy.title}
      message={message}
      primary={{ label: S.backHome, icon: 'home-outline', onPress: onHome }}
      secondary={{ label: S.editMore, icon: 'options-outline', onPress: onClose }}
      onClose={onClose}>
      <View className="flex-row items-center gap-3">
        <IconBadge icon="hardware-chip-outline" tone={sync === 'applied' ? 'ontime' : 'late'} size="sm" />
        <View className="flex-1">
          <Text className="text-body font-bold text-ink" numberOfLines={1}>
            {deviceName}
          </Text>
          <View className="flex-row items-center gap-1.5">
            {sync === 'checking' && <ActivityIndicator size="small" color={tokens.colors.late.fg} />}
            <Text className={`text-body-sm font-semibold ${sync === 'applied' ? 'text-ontime-fg' : 'text-late-fg'}`}>
              {device ? S.statusWithBattery(copy.status, formatBattery(device.batteryPercent)) : copy.status}
            </Text>
          </View>
        </View>
        <StatusPill label={S.activeSlots(active.length, slots.length)} tone={sync === 'applied' ? 'ontime' : 'late'} />
      </View>
      {active.length ? (
        active.map((slot, i) => <SyncedSlotRow key={slot.id} slot={slot} index={i} timezoneLabel={timezoneLabel} />)
      ) : (
        <Text className="text-body-sm text-ink-muted">{S.noActive}</Text>
      )}
      {minTolerance !== null && (
        <View className="flex-row items-center gap-2">
          <Icon name="notifications-outline" size={18} color={tokens.colors.ontime.fg} />
          <Text className="flex-1 text-body-sm text-ink-muted">{S.toleranceNote(minTolerance)}</Text>
        </View>
      )}
    </SuccessSheet>
  );
}
