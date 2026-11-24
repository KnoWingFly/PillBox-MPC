import { Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import type { GrantableRole, Member } from '@root/lib/members';

import { SegmentedChoice } from '../form/segmented-choice';
import { ListRow } from '../pillbox/blocks';
import { Dialog } from '../pillbox/dialog';
import { Button, Divider } from '../pillbox/ui';

const S = Strings.members;

const ACCESS_OPTIONS = [
  { value: 'ADMIN', label: Strings.shell.roles.ADMIN },
  { value: 'PEMANTAU', label: Strings.shell.roles.PEMANTAU },
] as const;

/** OWNER's actions on another member: change access (saved at once), make owner, remove. */
export function MemberActionsDialog({
  member,
  busy,
  onChangeRole,
  onMakeOwner,
  onRemove,
  onClose,
}: {
  /** null = hidden. Never the OWNER (the owner has no row actions). */
  member: Member | null;
  busy: boolean;
  onChangeRole: (member: Member, role: GrantableRole) => void;
  onMakeOwner: (member: Member) => void;
  onRemove: (member: Member) => void;
  onClose: () => void;
}) {
  const role = member && member.role !== 'OWNER' ? member.role : null;
  return (
    <Dialog visible={member !== null} busy={busy} onCancel={onClose}>
      {member && role && (
        <View className="gap-4">
          <View className="gap-0.5">
            <Text className="text-heading font-bold text-ink" accessibilityRole="header" numberOfLines={1}>
              {member.full_name}
            </Text>
            {member.relationship_label ? (
              <Text className="text-body-sm text-ink-muted">{member.relationship_label}</Text>
            ) : null}
          </View>
          <SegmentedChoice
            label={S.access}
            options={ACCESS_OPTIONS}
            value={role}
            disabled={busy}
            onChange={(next) => {
              if (next !== role) onChangeRole(member, next);
            }}
          />
          <Text className="text-body-sm text-ink-muted">{S.roleShort[role]}</Text>
          <Divider />
          <View>
            <ListRow icon="star-outline" title={S.makeOwner} onPress={busy ? undefined : () => onMakeOwner(member)} />
            <ListRow
              icon="person-remove-outline"
              tone="missed"
              title={S.remove}
              onPress={busy ? undefined : () => onRemove(member)}
            />
          </View>
          <Button label={Strings.common.close} variant="secondary" onPress={onClose} disabled={busy} />
        </View>
      )}
    </Dialog>
  );
}
