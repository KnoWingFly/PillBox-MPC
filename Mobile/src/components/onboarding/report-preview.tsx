import { Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';

import { Icon, IconBadge, StatusPill } from '../pillbox/ui';
import { PreviewCard, PreviewFrame } from './preview-parts';

const S = Strings.onboarding.report;

/** Slide 3: weekly compliance report, PDF export and the care team. */
export function ReportPreview() {
  return (
    <PreviewFrame>
      <PreviewCard>
        <View className="flex-row items-center gap-3">
          <IconBadge icon="calendar-outline" tone="primary" size="sm" />
          <View className="flex-1">
            <Text className="text-body-sm font-bold text-ink">{S.cardTitle}</Text>
            <Text className="text-caption text-ink-muted">{S.cardSubtitle}</Text>
          </View>
        </View>
        <View className="self-start">
          <StatusPill label={S.autoSync} tone="primary" />
        </View>

        <View className="gap-3 rounded-2xl bg-canvas p-3">
          <View className="flex-row items-center justify-between">
            <View className="gap-1">
              <Text className="text-caption text-ink-muted">{S.rateLabel}</Text>
              <View className="flex-row items-center gap-2">
                <Text className="text-display font-bold text-primary">{S.rateValue}</Text>
                <StatusPill label={S.rateBadge} tone="ontime" />
              </View>
            </View>
            <View className="h-14 w-14 items-center justify-center rounded-full border-4 border-primary">
              <Icon name="ribbon-outline" size={22} color={tokens.colors.primary.DEFAULT} />
            </View>
          </View>
          <View className="flex-row gap-2">
            <StatTile label={S.onTime} value={S.onTimeCount} valueClassName="text-ontime-fg" />
            <StatTile label={S.late} value={S.lateCount} valueClassName="text-late-fg" />
            <StatTile label={S.missed} value={S.missedCount} valueClassName="text-ink" />
          </View>
        </View>

        <View className="flex-row items-center gap-3 rounded-2xl bg-primary-light p-3">
          <IconBadge icon="document-text-outline" tone="primary" size="sm" />
          <View className="flex-1">
            <Text className="text-body-sm font-bold text-ink">{S.exportTitle}</Text>
            <Text className="text-caption text-ink-muted">{S.exportText}</Text>
          </View>
          <Icon name="download-outline" size={20} color={tokens.colors.primary.DEFAULT} />
        </View>

        <View className="flex-row items-center gap-3 rounded-2xl bg-canvas p-3">
          <IconBadge icon="people-outline" tone="neutral" size="sm" />
          <Text className="flex-1 text-right text-caption font-semibold text-ink-muted">{S.team}</Text>
        </View>
      </PreviewCard>
    </PreviewFrame>
  );
}

function StatTile({ label, value, valueClassName }: { label: string; value: string; valueClassName: string }) {
  return (
    <View className="flex-1 items-center gap-1 rounded-xl bg-surface p-2">
      <Text className="text-center text-caption text-ink-muted">{label}</Text>
      <Text className={`text-body font-bold ${valueClassName}`}>{value}</Text>
    </View>
  );
}
