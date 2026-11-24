// Member actions on the Anggota screen. Every destructive one goes through a confirmation;
// each result is reported with a toast and the list is reloaded from the server.
import { useCallback, useState } from 'react';

import type { ConfirmRequest } from '@/components/pillbox/dialog';
import type { ToastTone } from '@/components/pillbox/helpers';
import { Strings } from '@/constants/strings';
import { errorMessage } from '@/lib/api/error-message';
import {
  changeMemberRole,
  removeMember,
  revokeInvitation,
  transferOwnership,
  type GrantableRole,
  type Member,
  type PendingInvitation,
} from '@root/lib/members';

const S = Strings.members;

export function useMemberActions({
  elderlyId,
  elderlyName,
  userId,
  reload,
  showToast,
  onLeft,
}: {
  elderlyId: string;
  elderlyName: string;
  userId: string | null;
  reload: () => Promise<void>;
  showToast: (text: string, tone: ToastTone) => void;
  /** The caller left the profile: the screen says so (a toast would vanish with the screen). */
  onLeft: () => void;
}) {
  /** Member whose action dialog is open (OWNER only). */
  const [selected, setSelected] = useState<Member | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);

  const attempt = useCallback(
    async (action: () => Promise<void>, success: string) => {
      try {
        await action();
        showToast(success, 'success');
      } catch (err) {
        showToast(errorMessage(err), 'error');
      }
      await reload();
    },
    [reload, showToast],
  );

  const changeRole = useCallback(
    async (member: Member, role: GrantableRole) => {
      setBusy(true);
      await attempt(async () => {
        await changeMemberRole(elderlyId, member.caregiver_id, role);
      }, S.roleChanged(member.full_name, Strings.shell.roles[role]));
      setBusy(false);
      setSelected(null);
    },
    [attempt, elderlyId],
  );

  const askMakeOwner = useCallback(
    (member: Member) => {
      setSelected(null);
      setConfirm({
        title: S.confirmOwnerTitle(member.full_name),
        message: S.confirmOwnerText,
        confirmLabel: S.confirmOwner,
        tone: 'warning',
        icon: 'star',
        onConfirm: () =>
          attempt(() => transferOwnership(elderlyId, member.caregiver_id), S.ownerChanged(member.full_name)),
      });
    },
    [attempt, elderlyId],
  );

  const askRemove = useCallback(
    (member: Member) => {
      setSelected(null);
      setConfirm({
        title: S.confirmRemoveTitle(member.full_name),
        message: S.confirmRemoveText(elderlyName),
        confirmLabel: S.remove,
        tone: 'danger',
        icon: 'person-remove-outline',
        onConfirm: () => attempt(() => removeMember(elderlyId, member.caregiver_id), S.removed(member.full_name)),
      });
    },
    [attempt, elderlyId, elderlyName],
  );

  const askLeave = useCallback(() => {
    if (!userId) return;
    setConfirm({
      title: S.confirmLeaveTitle,
      message: S.confirmLeaveText(elderlyName),
      confirmLabel: S.confirmLeave,
      tone: 'danger',
      icon: 'exit-outline',
      onConfirm: async () => {
        try {
          await removeMember(elderlyId, userId);
          onLeft();
        } catch (err) {
          showToast(errorMessage(err), 'error');
        }
      },
    });
  }, [elderlyId, elderlyName, onLeft, showToast, userId]);

  const askRevoke = useCallback(
    (invitation: PendingInvitation) => {
      setConfirm({
        title: S.confirmRevokeTitle,
        message: S.confirmRevokeText,
        confirmLabel: S.revoke,
        tone: 'danger',
        icon: 'close-circle-outline',
        onConfirm: () => attempt(() => revokeInvitation(elderlyId, invitation.invitation_id), S.revoked),
      });
    },
    [attempt, elderlyId],
  );

  const runConfirm = useCallback(async () => {
    if (!confirm || busy) return;
    setBusy(true);
    try {
      await confirm.onConfirm();
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  }, [busy, confirm]);

  return {
    selected,
    select: setSelected,
    busy,
    confirm,
    closeConfirm: () => setConfirm(null),
    runConfirm,
    changeRole,
    askMakeOwner,
    askRemove,
    askLeave,
    askRevoke,
  };
}
