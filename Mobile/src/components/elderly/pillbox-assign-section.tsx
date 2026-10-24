import { ActivityIndicator, Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';
import type { Pillbox } from '@root/lib/devices';

import { Button, Card, EmptyState, LoadErrorBox, StatusPill } from '../pillbox/ui';
import { PillboxOptionCard } from './pillbox-option-card';

const S = Strings.elderlyForm;

/**
 * "Tugaskan Dispenser Pillbox". Pillboxes belong to an elderly profile, so every one the caregiver
 * can list is already in use; new ones are paired (QR + PIN) after the profile is saved.
 * The list is short (the caregiver's own pillboxes), so it renders inside the form's ScrollView.
 */
export function PillboxAssignSection({
  pillboxes,
  loading,
  error,
  onRetry,
  onPairNew,
}: {
  pillboxes: Pillbox[] | null;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  onPairNew: () => void;
}) {
  let body;
  if (loading && !pillboxes) {
    body = <ActivityIndicator color={tokens.colors.primary.DEFAULT} accessibilityLabel={S.loadingPillboxes} />;
  } else if (error) {
    body = <LoadErrorBox text={S.loadError} onRetry={onRetry} />;
  } else if (!pillboxes?.length) {
    body = <EmptyState icon="cube-outline" title={S.emptyTitle} text={S.emptyText} />;
  } else {
    body = (
      <View className="gap-3">
        {pillboxes.map((p) => (
          <PillboxOptionCard key={p.id} pillbox={p} />
        ))}
      </View>
    );
  }

  return (
    <Card
      title={S.pillboxSection}
      icon="cube-outline"
      right={<StatusPill label={S.multiDeviceBadge} tone="info" icon="albums-outline" />}>
      <Text className="text-body-sm text-ink-muted">{S.pillboxSectionHint}</Text>
      {body}
      <Button label={S.pairNew} variant="secondary" onPress={onPairNew} />
    </Card>
  );
}
