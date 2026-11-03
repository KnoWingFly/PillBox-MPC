import { Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';

import { Icon, IconBadge, StatusPill, type IconName, type Tone } from '../pillbox/ui';
import { PreviewCard, PreviewFrame, PreviewPill } from './preview-parts';

const S = Strings.onboarding.escalation;

/** Slide 2: alarm -> app reminder -> WhatsApp escalation timeline. */
export function EscalationPreview() {
  return (
    <PreviewFrame>
      <View className="flex-row items-center justify-between">
        <PreviewPill label={S.header} icon="flash" iconColor={tokens.colors.late.solid} />
        <PreviewPill label={S.live} dot />
      </View>

      <TimelineStep icon="notifications-outline" tone="neutral" time={S.alarmTime} title={S.alarmTitle} text={S.alarmText} status={S.alarmStatus} />
      <StepGap label={S.gapPause} />
      <TimelineStep icon="phone-portrait-outline" tone="primary" time={S.reminderTime} title={S.reminderTitle} text={S.reminderText} status={S.reminderStatus} />
      <StepGap label={S.gapEscalate} />

      <PreviewCard className="border-l-4 border-ontime-solid">
        <View className="flex-row items-center justify-between gap-2">
          <View className="shrink flex-row items-center gap-2">
            <Icon name="logo-whatsapp" size={20} color={tokens.colors.ontime.solid} />
            <Text className="shrink text-body-sm font-bold text-ontime-fg">{S.whatsappTitle}</Text>
          </View>
          <Text className="text-caption font-semibold text-ontime-fg">{S.whatsappTime}</Text>
        </View>
        <View className="gap-1.5 rounded-2xl bg-ontime-soft p-3">
          <View className="flex-row items-center justify-between gap-2">
            <View className="flex-row items-center gap-1">
              <Text className="text-caption font-bold text-ontime-fg">{S.botName}</Text>
              <Icon name="checkmark-circle-outline" size={14} color={tokens.colors.ontime.fg} />
            </View>
            <View className="flex-row items-center gap-1">
              <Icon name="checkmark-done" size={14} color={tokens.colors.ontime.fg} />
              <Text className="text-caption text-ontime-fg">{S.priority}</Text>
            </View>
          </View>
          <Text className="text-caption text-ink">{S.botMessage}</Text>
        </View>
      </PreviewCard>

      <View className="self-center">
        <PreviewPill label={S.successRate} icon="shield-checkmark" iconColor={tokens.colors.ontime.solid} />
      </View>
    </PreviewFrame>
  );
}

function TimelineStep({ icon, tone, time, title, text, status }: {
  icon: IconName;
  tone: Tone;
  time: string;
  title: string;
  text: string;
  status: string;
}) {
  return (
    <PreviewCard className="flex-row items-start">
      <IconBadge icon={icon} tone={tone} size="sm" />
      <View className="flex-1 gap-0.5">
        <View className="flex-row items-center justify-between gap-2">
          <Text className={`text-caption font-semibold ${tone === 'primary' ? 'text-primary' : 'text-ink-muted'}`}>{time}</Text>
          <StatusPill label={status} tone={tone} icon={tone === 'primary' ? 'send' : 'checkmark'} />
        </View>
        <Text className="text-body-sm font-bold text-ink">{title}</Text>
        <Text className="text-caption text-ink-muted" numberOfLines={1}>
          {text}
        </Text>
      </View>
    </PreviewCard>
  );
}

function StepGap({ label }: { label: string }) {
  return (
    <View className="flex-row items-center gap-2 pl-4">
      <View className="h-4 w-0.5 bg-primary" />
      <Text className="text-caption font-semibold text-ink-muted">{label}</Text>
    </View>
  );
}
