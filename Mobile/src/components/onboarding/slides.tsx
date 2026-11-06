// The onboarding pages, in order. Used by the onboarding pager and by the rotating panel beside
// the auth forms on wide screens.
import type { ComponentType } from 'react';

import { Strings } from '@/constants/strings';

import type { IconName } from '../pillbox/ui';
import { EscalationPreview } from './escalation-preview';
import { MonitoringPreview } from './monitoring-preview';
import { OnboardingSlide } from './onboarding-slide';
import { ReportPreview } from './report-preview';

const S = Strings.onboarding;

export type OnboardingContent = {
  key: string;
  Preview: ComponentType;
  badge: string;
  badgeIcon: IconName;
  title: string;
  body: string;
  /** Center the text on phones (the first slide is left-aligned, as in the design). */
  centered: boolean;
};

export const ONBOARDING_CONTENT: readonly OnboardingContent[] = [
  { key: 'monitoring', Preview: MonitoringPreview, badgeIcon: 'radio-outline', centered: false, ...S.monitoring },
  { key: 'escalation', Preview: EscalationPreview, badgeIcon: 'alert-circle-outline', centered: true, ...S.escalation },
  { key: 'report', Preview: ReportPreview, badgeIcon: 'bar-chart-outline', centered: true, ...S.report },
];

export const ONBOARDING_SLIDES = ONBOARDING_CONTENT.map(({ key, Preview, badge, badgeIcon, title, body, centered }) => (
  <OnboardingSlide
    key={key}
    preview={<Preview />}
    badge={badge}
    badgeIcon={badgeIcon}
    title={title}
    body={body}
    centered={centered}
  />
));
