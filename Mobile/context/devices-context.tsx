// The caregiver's pillboxes and which one is active. Every dashboard screen is scoped to the
// active pillbox: the dashboard is keyed by its id (src/app/index.tsx), and lib/api.ts targets it
// for every device-scoped call and filters the notification stream by it.
//
// Changes are optimistic: the list updates at once and rolls back if lib/devices.ts throws.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type PropsWithChildren } from 'react';

import { AppConfig } from '@/config';
import { useAuth } from '@/hooks/use-auth';
import * as api from '@root/lib/api';
import * as devices from '@root/lib/devices';
import type { Pillbox } from '@root/lib/devices';

/** Background refresh of the list (online state, battery) while the dashboard is open. */
const LIST_REFRESH_MS = 30_000;

type DevicesValue = {
  /** Visible pillboxes (hidden ones excluded); null until the first load finishes. */
  pillboxes: Pillbox[] | null;
  /** Pillboxes hidden on this phone. */
  hidden: Pillbox[];
  /** Every pillbox on the account, hidden included (duplicate checks). */
  all: Pillbox[];
  active: Pillbox | null;
  /** The first load failed and there is nothing to show. */
  loadError: boolean;
  refresh: () => Promise<void>;
  select: (id: string) => void;
  /** After pairing or joining: reloads the list and makes the new pillbox active. */
  added: (deviceId: string) => Promise<void>;
  /** Resolves false (and restores the old name) when the server refused. */
  rename: (id: string, name: string) => Promise<boolean>;
  /** Unpair (OWNER). Resolves null on failure (list restored), else the notification purge result. */
  remove: (pillbox: Pillbox) => Promise<{ notificationsFailed: number } | null>;
  hide: (id: string) => Promise<boolean>;
  unhideAll: () => Promise<void>;
};

const DevicesContext = createContext<DevicesValue | null>(null);

export function useDevices(): DevicesValue {
  const ctx = useContext(DevicesContext);
  if (!ctx) throw new Error('useDevices must be used inside <DevicesProvider>');
  return ctx;
}

/** Saved choice if still visible, else the configured pin, else the first one. */
function pickActive(visible: Pillbox[], preferred: string | null): Pillbox | null {
  return (
    visible.find((p) => p.id === preferred) ??
    visible.find((p) => p.id === AppConfig.pinnedDeviceId) ??
    visible[0] ??
    null
  );
}

export function DevicesProvider({ children }: PropsWithChildren) {
  const { user } = useAuth();
  const userId = user?.id ?? 'anonymous';
  const [all, setAll] = useState<Pillbox[] | null>(null);
  const [hiddenIds, setHiddenIds] = useState<string[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);

  // Latest values for async callbacks (rollbacks must restore what was there, not a stale render).
  const stateRef = useRef({ all, hiddenIds, activeId });
  useEffect(() => {
    stateRef.current = { all, hiddenIds, activeId };
  }, [all, hiddenIds, activeId]);

  // A list fetched while a rename/remove is in flight can predate that change and would put the
  // old state back. `epoch` bumps when a change starts and when it ends: a list response is only
  // applied if no change started or finished while it was loading.
  const mutating = useRef(0);
  const epoch = useRef(0);
  const beginMutation = () => {
    mutating.current += 1;
    epoch.current += 1;
  };
  const endMutation = () => {
    mutating.current -= 1;
    epoch.current += 1;
  };

  /**
   * The single place the active pillbox changes. lib/api.ts is updated BEFORE React state, so the
   * dashboard that remounts for the new id already targets it in its first effects.
   */
  const applyActive = useCallback(
    (next: Pillbox | null) => {
      api.setActivePillbox(next ? { id: next.id, elderlyId: next.elderlyId } : null);
      stateRef.current = { ...stateRef.current, activeId: next?.id ?? null };
      setActiveId(next?.id ?? null);
      void devices.saveActivePillboxId(userId, next?.id ?? null);
    },
    [userId],
  );

  const applyList = useCallback(
    (list: Pillbox[], hidden: string[], preferred: string | null) => {
      const visible = list.filter((p) => !hidden.includes(p.id));
      const current = visible.find((p) => p.id === preferred);
      // Same pillbox still active: only refresh lib/api.ts (its elderly may have changed).
      if (current && current.id === stateRef.current.activeId) {
        api.setActivePillbox({ id: current.id, elderlyId: current.elderlyId });
      } else applyActive(pickActive(visible, preferred));
      setAll(list);
      setHiddenIds(hidden);
    },
    [applyActive],
  );

  const refresh = useCallback(async () => {
    if (mutating.current > 0) return; // the change in flight reconciles with the server itself
    const startedAt = epoch.current;
    try {
      const list = await devices.listPillboxes();
      if (startedAt !== epoch.current) return; // a change happened meanwhile: this list may be stale
      setLoadError(false);
      applyList(list, stateRef.current.hiddenIds, stateRef.current.activeId);
    } catch {
      if (stateRef.current.all === null) setLoadError(true);
    }
  }, [applyList]);

  // First load: saved choices for this account, then the list.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [saved, hidden] = await Promise.all([
        devices.loadActivePillboxId(userId),
        devices.loadHiddenPillboxIds(userId),
      ]);
      try {
        const list = await devices.listPillboxes();
        if (cancelled) return;
        setLoadError(false);
        applyList(list, hidden, saved);
      } catch {
        if (!cancelled) setLoadError(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId, applyList]);

  useEffect(() => {
    if (api.USE_MOCK) return;
    const timer = setInterval(() => void refresh(), LIST_REFRESH_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const select = useCallback(
    (id: string) => {
      const target = stateRef.current.all?.find((p) => p.id === id);
      if (target && id !== stateRef.current.activeId) applyActive(target);
    },
    [applyActive],
  );

  const added = useCallback(
    async (deviceId: string) => {
      const hidden = stateRef.current.hiddenIds.filter((id) => id !== deviceId);
      if (hidden.length !== stateRef.current.hiddenIds.length) await devices.saveHiddenPillboxIds(userId, hidden);
      const list = await devices.listPillboxes();
      setLoadError(false);
      applyList(list, hidden, deviceId);
    },
    [applyList, userId],
  );

  /**
   * After a failed write, the server may still have applied it (a timeout, or an error after the
   * commit): read the list back instead of assuming it did not. null = the server is unreachable.
   */
  const reconcile = useCallback(async (): Promise<Pillbox[] | null> => {
    try {
      const list = await devices.listPillboxes();
      applyList(list, stateRef.current.hiddenIds, stateRef.current.activeId);
      return list;
    } catch {
      return null;
    }
  }, [applyList]);

  const rename = useCallback(
    async (id: string, name: string) => {
      const before = stateRef.current.all;
      const wanted = name.trim();
      beginMutation();
      setAll((prev) => prev?.map((p) => (p.id === id ? { ...p, name: wanted } : p)) ?? prev);
      try {
        await devices.renamePillbox(id, wanted);
        return true;
      } catch {
        const server = await reconcile();
        if (server) return server.find((p) => p.id === id)?.name === wanted;
        setAll(before);
        return false;
      } finally {
        endMutation();
      }
    },
    [reconcile],
  );

  const remove = useCallback(
    async (pillbox: Pillbox) => {
      const { all: before, hiddenIds: hidden, activeId: wasActive } = stateRef.current;
      const rest = (before ?? []).filter((p) => p.id !== pillbox.id);
      beginMutation();
      setAll(rest);
      if (wasActive === pillbox.id) applyActive(pickActive(rest.filter((p) => !hidden.includes(p.id)), null));
      try {
        const result = await devices.unpairPillbox(pillbox);
        api.markPillboxRemoved(pillbox.id); // late pushes about it are ignored from now on
        return { notificationsFailed: result.notificationsFailed };
      } catch {
        // Gone on the server after all (the unpair committed, the response was lost): it worked,
        // but this account's notification history for it was not purged.
        const server = await reconcile();
        if (server && !server.some((p) => p.id === pillbox.id)) {
          api.markPillboxRemoved(pillbox.id);
          return { notificationsFailed: -1 };
        }
        if (!server) setAll(before);
        if (wasActive === pillbox.id) applyActive(pillbox);
        return null;
      } finally {
        endMutation();
      }
    },
    [applyActive, reconcile],
  );

  const hide = useCallback(
    async (id: string) => {
      const { all: list, hiddenIds: before, activeId: wasActive } = stateRef.current;
      const next = [...before.filter((x) => x !== id), id];
      setHiddenIds(next);
      if (wasActive === id) applyActive(pickActive((list ?? []).filter((p) => !next.includes(p.id)), null));
      try {
        await devices.saveHiddenPillboxIds(userId, next);
        return true;
      } catch {
        setHiddenIds(before);
        const restored = list?.find((p) => p.id === wasActive);
        if (wasActive === id && restored) applyActive(restored);
        return false;
      }
    },
    [applyActive, userId],
  );

  const unhideAll = useCallback(async () => {
    setHiddenIds([]);
    await devices.saveHiddenPillboxIds(userId, []).catch(() => undefined);
    if (!stateRef.current.activeId) applyActive(pickActive(stateRef.current.all ?? [], null));
  }, [applyActive, userId]);

  const value = useMemo<DevicesValue>(() => {
    const list = all ?? [];
    return {
      pillboxes: all === null ? null : list.filter((p) => !hiddenIds.includes(p.id)),
      hidden: list.filter((p) => hiddenIds.includes(p.id)),
      all: list,
      active: list.find((p) => p.id === activeId && !hiddenIds.includes(p.id)) ?? null,
      loadError,
      refresh,
      select,
      added,
      rename,
      remove,
      hide,
      unhideAll,
    };
  }, [all, hiddenIds, activeId, loadError, refresh, select, added, rename, remove, hide, unhideAll]);

  return <DevicesContext.Provider value={value}>{children}</DevicesContext.Provider>;
}
