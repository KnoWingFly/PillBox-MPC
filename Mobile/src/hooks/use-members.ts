// Members and pending invitations of one elderly profile, kept fresh by the backend's "roles" push.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { AppConfig } from '@/config';
import { useAuth } from '@/hooks/use-auth';
import { usePolling } from '@/hooks/use-polling';
import { BackendError, subscribeToRoleChanges } from '@root/lib/api';
import type { PillboxRole } from '@root/lib/devices';
import { canInvite, listMembers, listPendingInvitations, type Member, type PendingInvitation } from '@root/lib/members';

const ROLE_ORDER: Record<PillboxRole, number> = { OWNER: 0, ADMIN: 1, PEMANTAU: 2 };

/** Owner first, then managers, then monitors; oldest member first within a role. */
function sortMembers(list: Member[]): Member[] {
  return [...list].sort(
    (a, b) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role] || a.added_at.localeCompare(b.added_at),
  );
}

async function fetchMembers(
  elderlyId: string,
  userId: string | null,
): Promise<{ members: Member[]; invitations: PendingInvitation[] }> {
  const list = await listMembers(elderlyId);
  const role = list.find((m) => m.caregiver_id === userId)?.role ?? null;
  // Only those who can invite may list invitations (the backend answers 403 otherwise).
  const invitations = canInvite(role) ? await listPendingInvitations(elderlyId) : [];
  return { members: sortMembers(list), invitations };
}

export type MembersState = {
  /** null until the first load finishes. */
  members: Member[] | null;
  invitations: PendingInvitation[];
  /** The signed-in caregiver's role on this profile; null when unknown (or no longer a member). */
  myRole: PillboxRole | null;
  userId: string | null;
  loadError: boolean;
  /** The caller is not a member (anymore): removed, or the profile was deleted (404). */
  noAccess: boolean;
  refreshing: boolean;
  /** Pull to refresh and after an action: shows the spinner until the list is back. */
  reload: () => Promise<void>;
};

export function useMembers(elderlyId: string): MembersState {
  const { user } = useAuth();
  const userId = user?.id ?? null;
  const [members, setMembers] = useState<Member[] | null>(null);
  const [invitations, setInvitations] = useState<PendingInvitation[]>([]);
  const [loadError, setLoadError] = useState(false);
  const [noAccess, setNoAccess] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  // Only the newest request may apply its result (a push can overlap a pull to refresh).
  const generation = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback((): Promise<void> => {
    const mine = ++generation.current;
    const current = () => mounted.current && mine === generation.current;
    return fetchMembers(elderlyId, userId).then(
      (result) => {
        if (!current()) return;
        setMembers(result.members);
        setInvitations(result.invitations);
        setLoadError(false);
        setNoAccess(false);
      },
      (err: unknown) => {
        if (!current()) return;
        if (err instanceof BackendError && err.status === 404) setNoAccess(true);
        else setLoadError(true);
      },
    );
  }, [elderlyId, userId]);

  const reload = useCallback(async () => {
    setRefreshing(true);
    try {
      await load();
    } finally {
      if (mounted.current) setRefreshing(false);
    }
  }, [load]);

  useEffect(() => {
    void load();
  }, [load]);

  // Someone joined, left or got another role: the backend pushes {"type":"roles"}. The push needs the
  // app's realtime socket, which is closed while the account has no pillbox: polling is the fallback.
  useEffect(() => subscribeToRoleChanges(() => void load()), [load]);
  usePolling(load, AppConfig.deviceListRefreshMs);

  const myRole = useMemo(() => members?.find((m) => m.caregiver_id === userId)?.role ?? null, [members, userId]);

  return { members, invitations, myRole, userId, loadError, noAccess, refreshing, reload };
}
