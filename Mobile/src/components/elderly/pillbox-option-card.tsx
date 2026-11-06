import { memo } from 'react';
import { Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';
import type { Pillbox } from '@root/lib/devices';

import { Icon, StatusPill } from '../pillbox/ui';

const S = Strings.elderlyForm;

/** A pillbox with no elderly profile can be assigned; one paired to a profile cannot (no transfer). */
export function isPillboxAvailable(pillbox: Pillbox): boolean {
  return pillbox.elderlyId === null;
}

/**
 * One pillbox in "Tugaskan Dispenser Pillbox": checkbox look, name, availability, code, battery, Wi-Fi.
 * Read-only: pillboxes are added to a profile by pairing after it is saved, so nothing is selected here.
 */
export const PillboxOptionCard = memo(function PillboxOptionCard({ pillbox }: { pillbox: Pillbox }) {
  const available = isPillboxAvailable(pillbox);
  const usedBy = pillbox.elderlyName ? S.usedBy(pillbox.elderlyName) : S.usedByUnknown;
  const status = available ? S.available : S.unavailable;

  return (
    <View
      accessible
      accessibilityLabel={S.pillboxA11y(pillbox.name, status, available ? null : usedBy)}
      accessibilityState={{ disabled: true }}
      className={`flex-row gap-3 rounded-2xl border border-line bg-surface p-4 ${available ? '' : 'opacity-60'}`}>
      <Icon name="square-outline" size={24} color={tokens.colors.ink.subtle} />
      <View className="flex-1 gap-1.5">
        <View className="flex-row flex-wrap items-center justify-between gap-2">
          <Text className="flex-shrink text-body font-semibold text-ink" numberOfLines={1}>
            {pillbox.name}
          </Text>
          <StatusPill label={status} tone={available ? 'ontime' : 'missed'} />
        </View>
        <Text className="text-body-sm text-ink-muted">{pillbox.code}</Text>
        <View className="flex-row flex-wrap gap-x-4 gap-y-1">
          {pillbox.batteryPercent !== null && (
            <View className="flex-row items-center gap-1">
              <Icon name="battery-half-outline" size={18} color={tokens.colors.battery.fg} />
              <Text className="text-body-sm text-battery-fg">{S.batteryLabel(pillbox.batteryPercent)}</Text>
            </View>
          )}
          <View className="flex-row items-center gap-1">
            <Icon name={pillbox.online ? 'wifi' : 'wifi-outline'} size={18} color={tokens.colors.ink.muted} />
            <Text className="text-body-sm text-ink-muted">{S.wifiLabel(pillbox.online)}</Text>
          </View>
        </View>
        {!available && <Text className="text-body-sm text-missed-fg">{usedBy}</Text>}
      </View>
    </View>
  );
});
