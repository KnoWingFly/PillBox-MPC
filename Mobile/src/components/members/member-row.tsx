import { memo } from 'react';
import { Pressable, Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';
import type { Member } from '@root/lib/members';

import { Avatar } from '../pillbox/blocks';
import { Icon } from '../pillbox/ui';
import { RoleBadge } from './role-badge';

const S = Strings.members;

/** Avatar, name (+ "Anda"), relationship and role. The "more" button appears only when the
 * viewer can act on this member, so a row never offers what the backend would refuse. */
export const MemberRow = memo(function MemberRow({
  member,
  isMe,
  onMore,
}: {
  member: Member;
  isMe: boolean;
  /** Omitted when there is nothing this viewer can do with the member. */
  onMore?: (member: Member) => void;
}) {
  const role = Strings.shell.roles[member.role];
  return (
    <View
      className="min-h-[64px] flex-row items-center gap-3 py-2"
      accessible={!onMore}
      accessibilityLabel={S.rowA11y(isMe ? `${member.full_name}, ${S.you}` : member.full_name, role)}>
      <Avatar name={member.full_name} />
      <View className="flex-1 gap-0.5">
        <Text className="text-body font-semibold text-ink" numberOfLines={1}>
          {member.full_name}
          {isMe ? <Text className="font-normal text-ink-muted">{` · ${S.you}`}</Text> : null}
        </Text>
        {member.relationship_label ? (
          <Text className="text-body-sm text-ink-muted" numberOfLines={1}>
            {member.relationship_label}
          </Text>
        ) : null}
      </View>
      <RoleBadge role={member.role} />
      {onMore ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={S.moreA11y(member.full_name)}
          onPress={() => onMore(member)}
          hitSlop={8}
          className="h-11 w-11 items-center justify-center rounded-full active:opacity-75">
          <Icon name="ellipsis-horizontal" size={22} color={tokens.colors.ink.muted} />
        </Pressable>
      ) : null}
    </View>
  );
});
