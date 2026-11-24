import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ListRow } from '@/components/pillbox/blocks';
import { Button, Card, EmptyState, LoadErrorBox, StatusPill } from '@/components/pillbox/ui';
import { BackHeader } from '@/components/ui/back-header';
import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';
import { getElderlyProfile, type ElderlyProfile } from '@root/lib/elderly';

const S = Strings.elderlySchedule;

type Pillbox = ElderlyProfile['devices'][number];

/**
 * "Jadwal Obat" of one elderly profile. Schedules live on a pillbox, so this page leads there:
 * one pillbox opens its Jadwal tab directly, several ask which one, none offers pairing.
 * Reached after saving a new profile ("Atur jadwal obat").
 */
export default function ElderlyScheduleScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [profile, setProfile] = useState<ElderlyProfile | null>(null);
  const [loadError, setLoadError] = useState(false);
  const generation = useRef(0);

  // `at` makes the dashboard treat each visit as a new request (see PillboxGate in app/index.tsx).
  const openSchedule = useCallback(
    (pillbox: Pillbox) =>
      router.dismissTo({ pathname: '/', params: { tab: 'schedule', device: pillbox.id, at: String(Date.now()) } }),
    [router],
  );
  const pairPillbox = () => router.dismissTo({ pathname: '/', params: { pair: '1', at: String(Date.now()) } });
  const toDashboard = () => router.dismissTo('/');

  const load = useCallback(() => {
    const mine = ++generation.current;
    return getElderlyProfile(id).then(
      (result) => {
        if (mine !== generation.current) return;
        setLoadError(false);
        // Exactly one pillbox: nothing to choose, go straight to its schedule.
        if (result.devices.length === 1) openSchedule(result.devices[0]);
        else setProfile(result);
      },
      () => {
        if (mine === generation.current) setLoadError(true);
      },
    );
  }, [id, openSchedule]);

  useEffect(() => {
    void load();
  }, [load]);

  const name = profile ? profile.nickname || profile.full_name : null;

  return (
    <SafeAreaView className="flex-1 bg-canvas" edges={['top', 'left', 'right', 'bottom']}>
      <BackHeader title={S.title} onBack={toDashboard} />
      <ScrollView contentContainerClassName="gap-4 px-4 pb-8 pt-4" testID={`elderly-schedule-${id}`}>
        {loadError ? (
          <LoadErrorBox text={S.loadError} onRetry={() => void load()} />
        ) : profile === null ? (
          <View className="items-center gap-3 py-10">
            <ActivityIndicator color={tokens.colors.primary.DEFAULT} />
            <Text className="text-body-sm text-ink-muted">{S.opening}</Text>
          </View>
        ) : profile.devices.length === 0 ? (
          <Card>
            <EmptyState icon="hardware-chip-outline" title={S.noPillboxTitle} text={S.noPillboxText} />
            <Button label={S.pairPillbox} icon="qr-code-outline" onPress={pairPillbox} />
            <Button label={S.backToDashboard} variant="secondary" onPress={toDashboard} />
          </Card>
        ) : (
          <Card title={name ?? S.choosePillbox} subtitle={S.choosePillboxText} icon="calendar-outline">
            {profile.devices.map((p) => (
              <ListRow
                key={p.id}
                icon="hardware-chip-outline"
                title={p.device_nickname || S.pillboxFallback}
                right={
                  <StatusPill
                    label={p.connectivity === 'ONLINE' ? S.online : S.offline}
                    tone={p.connectivity === 'ONLINE' ? 'ontime' : 'neutral'}
                  />
                }
                onPress={() => openSchedule(p)}
              />
            ))}
          </Card>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
