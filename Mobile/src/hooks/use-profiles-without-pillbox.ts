// Elderly profiles the caregiver belongs to that have no pillbox yet. The dashboard only reaches a
// profile through its pillbox, so these would otherwise be invisible (e.g. right after joining
// with an invitation code, before the owner pairs a pillbox).
import { useCallback, useEffect, useRef, useState } from 'react';

import { subscribeToRoleChanges, USE_MOCK } from '@root/lib/api';
import { listMyElderly, type ElderlySummary } from '@root/lib/elderly';

/** `refreshKey`: reload when it changes (e.g. the active pillbox, after a pairing). */
export function useProfilesWithoutPillbox(refreshKey?: string | null): ElderlySummary[] {
  const [profiles, setProfiles] = useState<ElderlySummary[]>([]);
  const generation = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback((): Promise<void> => {
    if (USE_MOCK) return Promise.resolve();
    const mine = ++generation.current;
    return listMyElderly().then(
      (list) => {
        if (mounted.current && mine === generation.current) setProfiles(list.filter((p) => p.device_count === 0));
      },
      () => {
        // Optional extra: on failure keep what was shown; the next push or refresh retries.
      },
    );
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  // Joined, left or removed: the backend pushes {"type":"roles"}.
  useEffect(() => subscribeToRoleChanges(() => void load()), [load]);

  return profiles;
}
