import { Strings } from '@/constants/strings';
import type { PillboxRole } from '@root/lib/devices';

import { StatusPill, type IconName, type Tone } from '../pillbox/ui';

/** One icon and one tone per role, used everywhere a role is shown. */
export const ROLE_LOOK: Record<PillboxRole, { icon: IconName; tone: Tone }> = {
  OWNER: { icon: 'star', tone: 'primary' },
  ADMIN: { icon: 'shield-checkmark', tone: 'info' },
  PEMANTAU: { icon: 'eye', tone: 'neutral' },
};

export function RoleBadge({ role }: { role: PillboxRole }) {
  const look = ROLE_LOOK[role];
  return <StatusPill label={Strings.shell.roles[role]} tone={look.tone} icon={look.icon} />;
}
