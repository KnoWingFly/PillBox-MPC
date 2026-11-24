import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { InviteDialog } from '@/components/members/invite-dialog';
import { MemberActionsDialog } from '@/components/members/member-actions-dialog';
import { MemberRow } from '@/components/members/member-row';
import { ROLE_LOOK } from '@/components/members/role-badge';
import { RoleInfoDialog } from '@/components/members/role-info-dialog';
import { daysLeft } from '@/components/members/time';
import { ListRow, TextLink } from '@/components/pillbox/blocks';
import { ConfirmDialog } from '@/components/pillbox/dialog';
import { Button, Card, EmptyState, LoadErrorBox, StatusPill } from '@/components/pillbox/ui';
import { BackHeader } from '@/components/ui/back-header';
import { Strings } from '@/constants/strings';
import { useMemberActions } from '@/hooks/use-member-actions';
import { useMembers } from '@/hooks/use-members';
import { useToast } from '@/hooks/use-toast';
import * as tokens from '@/theme/tokens';
import { canInvite, canManageMembers, canRevoke, type Member, type PendingInvitation } from '@root/lib/members';

const S = Strings.members;

const keyOf = (m: Member) => m.caregiver_id;

/** "Anggota keluarga" of one elderly profile: who watches, with what access, and invitations. */
export default function MembersScreen() {
  const router = useRouter();
  // joined = "1": opened right after accepting an invitation code (says so with a toast).
  const { id, name, joined } = useLocalSearchParams<{ id: string; name?: string; joined?: string }>();
  const elderlyName = name || Strings.shell.elderlyFallback;
  const { members, invitations, myRole, userId, loadError, noAccess, refreshing, reload } = useMembers(id);
  const { showToast, toastNode } = useToast(joined ? { text: S.joined(elderlyName), tone: 'success' } : null);
  const [inviting, setInviting] = useState(false);
  const [showInfo, setShowInfo] = useState(false);
  // Set after "Keluar" succeeds: the screen then says so instead of showing the old list.
  const [left, setLeft] = useState(false);

  const goBack = useCallback(() => {
    if (router.canGoBack()) router.back();
    else router.replace('/');
  }, [router]);

  // The backend pushes {"type":"roles"}, so the dashboard reloads its pillbox list on its own.
  const onLeft = useCallback(() => setLeft(true), []);

  const actions = useMemberActions({ elderlyId: id, elderlyName, userId, reload, showToast, onLeft });
  const manage = canManageMembers(myRole);

  const renderItem = useCallback(
    ({ item }: { item: Member }) => (
      <MemberRow
        member={item}
        isMe={item.caregiver_id === userId}
        onMore={manage && item.role !== 'OWNER' ? actions.select : undefined}
      />
    ),
    [actions.select, manage, userId],
  );

  const header = (
    <View className="gap-2 pb-2">
      {loadError ? <LoadErrorBox text={S.loadError} onRetry={() => void reload()} /> : null}
      <View className="flex-row items-center justify-between">
        <Text className="text-body text-ink-muted" numberOfLines={1}>
          {elderlyName}
        </Text>
        {myRole === 'PEMANTAU' ? <StatusPill label={S.readOnly} tone="neutral" icon={ROLE_LOOK.PEMANTAU.icon} /> : null}
      </View>
    </View>
  );

  const footer = (
    <View className="gap-4 pt-2">
      {invitations.length > 0 && (
        <Card title={S.pending} icon="time-outline" tone="late">
          {invitations.map((inv: PendingInvitation) => (
            <ListRow
              key={inv.invitation_id}
              icon={ROLE_LOOK[inv.role].icon}
              tone={ROLE_LOOK[inv.role].tone}
              title={
                daysLeft(inv.expires_at) > 0
                  ? S.pendingRow(Strings.shell.roles[inv.role], daysLeft(inv.expires_at))
                  : S.pendingRowToday(Strings.shell.roles[inv.role])
              }
              subtitle={inv.relationship_label ?? inv.invited_by_name ?? undefined}
              right={
                canRevoke(myRole, userId, inv) ? (
                  <Button label={S.revokeShort} size="sm" variant="ghost" onPress={() => actions.askRevoke(inv)} />
                ) : undefined
              }
            />
          ))}
        </Card>
      )}
      <TextLink label={S.whatsDifferent} onPress={() => setShowInfo(true)} />
      {myRole && myRole !== 'OWNER' ? (
        <Button label={S.leave} icon="exit-outline" variant="danger-soft" onPress={actions.askLeave} />
      ) : null}
      {myRole === 'OWNER' && members && members.length > 1 ? (
        <Text className="text-caption text-ink-muted">{S.ownerCannotLeave}</Text>
      ) : null}
    </View>
  );

  return (
    <SafeAreaView className="flex-1 bg-canvas" edges={['top', 'left', 'right', 'bottom']}>
      <BackHeader title={S.title} onBack={goBack} />
      {left || noAccess ? (
        <View className="flex-1 justify-center gap-2 p-4">
          <EmptyState
            icon={left ? 'exit-outline' : 'lock-closed-outline'}
            title={left ? S.left(elderlyName) : S.noAccessTitle}
            text={left ? S.leftText : S.noAccessText}
          />
          <Button label={S.back} onPress={goBack} />
        </View>
      ) : members === null && !loadError ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color={tokens.colors.primary.DEFAULT} />
        </View>
      ) : members === null ? (
        <View className="p-4">
          <LoadErrorBox text={S.loadError} onRetry={() => void reload()} />
        </View>
      ) : (
        <FlatList
          data={members}
          keyExtractor={keyOf}
          renderItem={renderItem}
          ListHeaderComponent={header}
          ListFooterComponent={footer}
          contentContainerClassName="px-4 pb-8 pt-4"
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => void reload()} />}
        />
      )}
      {canInvite(myRole) && !left && !noAccess && (
        <View className="border-t border-line bg-surface px-4 py-3">
          <Button label={S.invite} icon="person-add-outline" onPress={() => setInviting(true)} />
        </View>
      )}

      <MemberActionsDialog
        member={actions.selected}
        busy={actions.busy}
        onChangeRole={(m, role) => void actions.changeRole(m, role)}
        onMakeOwner={actions.askMakeOwner}
        onRemove={actions.askRemove}
        onClose={() => actions.select(null)}
      />
      <InviteDialog
        visible={inviting}
        elderlyId={id}
        elderlyName={elderlyName}
        myRole={myRole}
        onCreated={() => void reload()}
        onClose={() => setInviting(false)}
      />
      <RoleInfoDialog visible={showInfo} onClose={() => setShowInfo(false)} />
      <ConfirmDialog
        request={actions.confirm}
        busy={actions.busy}
        onConfirm={() => void actions.runConfirm()}
        onCancel={actions.closeConfirm}
      />
      {toastNode}
    </SafeAreaView>
  );
}
