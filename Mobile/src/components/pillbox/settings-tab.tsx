import Constants from 'expo-constants';
import { ActivityIndicator, ScrollView, Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';
import type { Pillbox } from '@root/lib/devices';
import type { ElderlyDetail, NotificationPreferences, PreferenceToggle } from '@root/lib/insights';
import { SLOT_IDS, type DeviceStatus } from '@root/lib/types';

import { Avatar, ListRow, SectionTitle, SwitchRow } from './blocks';
import { ageInYears, batteryText, deviceLook } from './helpers';
import { Button, Card, Divider, LoadErrorBox, ScreenHeader, StatusPill } from './ui';

const S = Strings.settings;
const PREFERENCE_KEYS: PreferenceToggle[] = ['notify_on_missed', 'notify_on_taken', 'notify_on_device_offline', 'notify_on_low_battery'];

function AccountCard({
  name,
  email,
  accountId,
  role,
}: {
  name: string;
  email: string | null;
  accountId: string | null;
  role: Pillbox['myRole'];
}) {
  return (
    <Card>
      <View className="flex-row items-center gap-3">
        <Avatar name={name} size="lg" online />
        <View className="flex-1 gap-0.5">
          <View className="flex-row flex-wrap items-center gap-2">
            <Text className="text-title font-bold text-ink" numberOfLines={1}>
              {name}
            </Text>
            <StatusPill label={S.active} tone="ontime" />
          </View>
          {role && <Text className="text-body-sm font-semibold text-primary">{Strings.shell.roles[role]}</Text>}
          {email && (
            <Text className="text-body-sm text-ink-muted" numberOfLines={1}>
              {email}
            </Text>
          )}
        </View>
      </View>
      {accountId && (
        <Text className="text-caption text-ink-muted" selectable>
          {S.accountId}: <Text className="font-semibold text-ink">{accountId}</Text>
        </Text>
      )}
    </Card>
  );
}

function ElderlyCard({
  elderly,
  pillbox,
  nowMs,
  onCall,
  onSwitch,
  onAdd,
}: {
  elderly: ElderlyDetail | null;
  pillbox: Pillbox | null;
  nowMs: number;
  onCall: () => void;
  onSwitch: () => void;
  onAdd?: () => void;
}) {
  const name = elderly?.fullName ?? pillbox?.elderlyName ?? null;
  const age = ageInYears(elderly?.birthDate ?? null, nowMs);
  return (
    <Card>
      {name ? (
        <View className="flex-row items-center gap-3">
          <Avatar name={name} size="lg" online={pillbox?.online ?? false} />
          <View className="flex-1 gap-0.5">
            <Text className="text-title font-bold text-ink">{name}</Text>
            {pillbox && <Text className="text-body-sm text-ink-muted">{S.dispenserLine(pillbox.name)}</Text>}
          </View>
          {age !== null && <StatusPill label={Strings.shell.ageYears(age)} tone="neutral" />}
        </View>
      ) : (
        <Text className="text-body text-ink-muted">{S.noElderly}</Text>
      )}
      {elderly?.contactPhone && (
        <ListRow icon="call-outline" tone="missed" title={S.callElder} subtitle={elderly.contactPhone} onPress={onCall} />
      )}
      <View className="gap-2">
        <Button label={S.switchProfile} icon="swap-horizontal" variant="secondary" size="sm" onPress={onSwitch} />
        {onAdd && <Button label={S.addElderly} icon="person-add-outline" variant="secondary" size="sm" onPress={onAdd} />}
      </View>
    </Card>
  );
}

function DeviceCard({
  device,
  now,
  onOpen,
  onAdd,
}: {
  device: DeviceStatus | null;
  now: number;
  onOpen: () => void;
  onAdd?: () => void;
}) {
  const look = device ? deviceLook(device, now) : null;
  const open = device?.openSlots ?? [];
  return (
    <Card>
      {device && look && (
        <ListRow
          icon="cube"
          tone={look.tone}
          title={device.deviceName}
          subtitle={`${batteryText(device.batteryPercent)} · ${device.online ? device.wifiLabel : Strings.device.noNetwork}`}
          onPress={onOpen}
        />
      )}
      {device && <Divider />}
      {device && (
        <ListRow
          icon="scan-outline"
          tone={open.length ? 'late' : 'ontime'}
          title={S.compartments}
          subtitle={open.length ? S.compartmentsOpen(open.join(', ')) : S.compartmentsClosed(SLOT_IDS.length, SLOT_IDS.length)}
          subtitleClassName={open.length ? 'text-late-fg' : 'text-ontime-fg'}
          onPress={onOpen}
        />
      )}
      {onAdd && <ListRow icon="add-circle-outline" title={S.addDevice} subtitle={S.addDeviceText} onPress={onAdd} />}
    </Card>
  );
}

function PreferencesCard({
  prefs,
  error,
  busy,
  onToggle,
  onRetry,
}: {
  prefs: NotificationPreferences | null;
  /** The last load failed (shown instead of an endless spinner). */
  error: boolean;
  busy: PreferenceToggle | null;
  onToggle: (key: PreferenceToggle, value: boolean) => void;
  onRetry: () => void;
}) {
  return (
    <Card>
      {prefs === null && error ? (
        <LoadErrorBox text={S.prefsLoadError} onRetry={onRetry} />
      ) : prefs === null ? (
        <ActivityIndicator color={tokens.colors.primary.DEFAULT} accessibilityLabel={S.prefsLoading} />
      ) : (
        PREFERENCE_KEYS.map((key) => (
          <SwitchRow
            key={key}
            title={S.prefs[key].title}
            text={S.prefs[key].text}
            value={prefs[key]}
            disabled={busy !== null}
            onChange={(value) => onToggle(key, value)}
          />
        ))
      )}
    </Card>
  );
}

export function SettingsTab({
  now,
  pillboxNow,
  userName,
  email,
  accountId,
  pillbox,
  elderly,
  device,
  prefs,
  prefsError,
  prefsBusy,
  onTogglePreference,
  onRetryPrefs,
  onCallElder,
  onOpenDevice,
  onAddElderly,
  onAddDevice,
  onSignOut,
}: {
  now: number;
  pillboxNow: number;
  userName: string;
  email: string | null;
  accountId: string | null;
  pillbox: Pillbox | null;
  elderly: ElderlyDetail | null;
  device: DeviceStatus | null;
  prefs: NotificationPreferences | null;
  prefsError: boolean;
  prefsBusy: PreferenceToggle | null;
  onTogglePreference: (key: PreferenceToggle, value: boolean) => void;
  onRetryPrefs: () => void;
  onCallElder: () => void;
  onOpenDevice: () => void;
  /** Omitted when profiles or pairing are unavailable (mock mode). */
  onAddElderly?: () => void;
  onAddDevice?: () => void;
  onSignOut: () => void;
}) {
  const version = Constants.expoConfig?.version;
  return (
    <ScrollView contentContainerClassName="gap-3 px-4 pb-8 pt-4">
      <ScreenHeader title={S.title} subtitle={S.subtitle} />
      <AccountCard name={userName} email={email} accountId={accountId} role={pillbox?.myRole ?? null} />

      <SectionTitle
        icon="accessibility-outline"
        title={S.elderlyTitle}
        right={elderly ? <Text className="text-caption text-ink-muted">{S.caregivers(elderly.caregiverCount)}</Text> : undefined}
      />
      <ElderlyCard elderly={elderly} pillbox={pillbox} nowMs={pillboxNow} onCall={onCallElder} onSwitch={onOpenDevice} onAdd={onAddElderly} />

      <SectionTitle
        icon="hardware-chip-outline"
        title={S.deviceTitle}
        right={device ? <StatusPill label={device.online ? Strings.shell.online : Strings.shell.offline} tone={device.online ? 'ontime' : 'missed'} /> : undefined}
      />
      <DeviceCard device={device} now={now} onOpen={onOpenDevice} onAdd={onAddDevice} />

      <SectionTitle icon="notifications-outline" title={S.notifyTitle} right={<Text className="text-caption text-ink-muted">{S.notifyHint}</Text>} />
      <PreferencesCard prefs={prefs} error={prefsError} busy={prefsBusy} onToggle={onTogglePreference} onRetry={onRetryPrefs} />

      <SectionTitle icon="help-circle-outline" title={S.aboutTitle} />
      <Card>
        <ListRow
          icon="information-circle-outline"
          tone="neutral"
          title={S.about}
          right={version ? <Text className="text-body-sm text-ink-muted">{S.version(version)}</Text> : undefined}
        />
      </Card>

      <View className="mt-2">
        <Button label={S.signOut} icon="log-out-outline" variant="danger-soft" onPress={onSignOut} />
      </View>
      <View className="items-center gap-1 py-4">
        <Text className="text-body-sm font-bold text-ink">{S.footerTitle}</Text>
        <Text className="text-center text-caption text-ink-muted">{S.footerText}</Text>
      </View>
    </ScrollView>
  );
}
