import { useRouter } from 'expo-router';

import { Strings } from '@/constants/strings';
import { useProfilesWithoutPillbox } from '@/hooks/use-profiles-without-pillbox';
import type { ElderlySummary } from '@root/lib/elderly';

import { ListRow } from '../pillbox/blocks';
import { Card } from '../pillbox/ui';
import { ROLE_LOOK } from './role-badge';

const S = Strings.members;

const displayName = (p: ElderlySummary) => p.nickname || p.full_name;

/**
 * Profiles the caregiver follows that have no pillbox yet, each opening its "Anggota keluarga"
 * screen. Renders nothing when there are none (and in mock mode).
 */
export function ProfilesWithoutPillboxCard({ refreshKey }: { refreshKey?: string | null }) {
  const router = useRouter();
  const profiles = useProfilesWithoutPillbox(refreshKey);
  if (profiles.length === 0) return null;
  return (
    <Card title={S.noPillboxTitle} subtitle={S.noPillboxText} icon="people-outline">
      {profiles.map((p) => (
        <ListRow
          key={p.id}
          icon={ROLE_LOOK[p.my_role].icon}
          tone={ROLE_LOOK[p.my_role].tone}
          title={displayName(p)}
          subtitle={S.noPillboxRow(Strings.shell.roles[p.my_role])}
          onPress={() =>
            router.push({ pathname: '/elderly/[id]/members', params: { id: p.id, name: displayName(p) } })
          }
        />
      ))}
    </Card>
  );
}
