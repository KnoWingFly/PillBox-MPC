import { useEffect, useRef, useState } from 'react';

import * as api from '@root/lib/api';
import {
  clearNotifications,
  compareFeed,
  deleteNotification,
  fetchNotificationPage,
  markNotificationRead,
  matchesFilter,
  type FeedPosition,
  type NotificationFilter,
} from '@root/lib/notifications';
import type { AppNotification } from '@root/lib/types';

export type FeedLoading = 'initial' | 'more' | 'refresh' | null;
export type FeedError = 'initial' | 'more' | null;

function newer(a: FeedPosition | null, b: FeedPosition | null): FeedPosition | null {
  if (!a) return b;
  if (!b) return a;
  return compareFeed(a, b) <= 0 ? a : b;
}

/**
 * Paginated notification feed (newest first) with live arrivals and optimistic delete / clear.
 *
 * Invariants:
 * - `items` is de-duplicated by id and always in feed order (merge, never append blindly).
 * - The cursor is the last item of the last fetched page, stored apart from `items`, so deleting
 *   or receiving items never moves it.
 * - Every reset (filter change, refresh, clear) bumps `generation`; responses from an older
 *   generation are dropped, and only one request per generation is in flight.
 * - Ids being deleted are skipped when pages come back, so a slow page can't resurrect them.
 */
export function useNotificationFeed({ onArrive }: { onArrive?: (n: AppNotification) => void } = {}) {
  const [filter, setFilterState] = useState<NotificationFilter>('all');
  const [items, setItems] = useState<AppNotification[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState<FeedLoading>('initial');
  const [error, setError] = useState<FeedError>(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const [latest, setLatest] = useState<FeedPosition | null>(null);
  const [clearing, setClearing] = useState(false);

  const filterRef = useRef<NotificationFilter>('all');
  const cursorRef = useRef<FeedPosition | null>(null);
  const generationRef = useRef(0);
  const inFlightRef = useRef<number | null>(null);
  const deletedIdsRef = useRef(new Set<string>());
  /** Live items received since the current first page was requested. */
  const arrivalsRef = useRef<AppNotification[]>([]);

  const merge = (current: AppNotification[], incoming: AppNotification[]) => {
    const byId = new Map(current.map((n) => [n.id, n]));
    for (const n of incoming) if (!deletedIdsRef.current.has(n.id)) byId.set(n.id, n);
    return [...byId.values()].sort(compareFeed);
  };

  /** Fetches page 1 for the current filter. Sets state only after the request settles. */
  const fetchFirst = async () => {
    const generation = ++generationRef.current;
    inFlightRef.current = generation;
    cursorRef.current = null;
    arrivalsRef.current = [];
    try {
      const page = await fetchNotificationPage({ filter: filterRef.current, cursor: null });
      if (generation !== generationRef.current) return;
      cursorRef.current = page.nextCursor;
      setItems(merge(page.items, arrivalsRef.current));
      setHasMore(page.nextCursor !== null);
      setUnreadCount(page.unreadCount);
      setLatest((prev) => newer(prev, page.latest));
      setLoading(null);
    } catch {
      if (generation !== generationRef.current) return;
      setError('initial');
      setLoading(null);
    } finally {
      if (inFlightRef.current === generation) inFlightRef.current = null;
    }
  };

  /** Called by onEndReached. After a failed page it waits for an explicit retry (`force`). */
  const loadMore = async (force = false) => {
    const generation = generationRef.current;
    const cursor = cursorRef.current;
    if (!hasMore || !cursor || inFlightRef.current === generation) return;
    if (error === 'initial' || (error === 'more' && !force)) return;
    inFlightRef.current = generation;
    setLoading('more');
    setError(null);
    try {
      const page = await fetchNotificationPage({ filter: filterRef.current, cursor });
      if (generation !== generationRef.current) return;
      cursorRef.current = page.nextCursor;
      setItems((prev) => merge(prev, page.items));
      setHasMore(page.nextCursor !== null);
      setUnreadCount(page.unreadCount);
      setLatest((prev) => newer(prev, page.latest));
      setLoading(null);
    } catch {
      if (generation !== generationRef.current) return;
      setError('more');
      setLoading(null);
    } finally {
      if (inFlightRef.current === generation) inFlightRef.current = null;
    }
  };

  /** `kind` only changes what the UI shows while page 1 loads. */
  const loadFirst = (kind: 'initial' | 'refresh') => {
    setLoading(kind);
    setError(null);
    return fetchFirst();
  };

  // First page on mount only (initial state is already "loading"); later loads come from
  // setFilter / refresh / retry.
  useEffect(() => {
    void fetchFirst();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(
    () =>
      api.subscribeToNotifications((n) => {
        setLatest((prev) => newer(prev, { createdAt: n.createdAt, id: n.id }));
        if (!n.read) setUnreadCount((c) => c + 1);
        if (matchesFilter(n, filterRef.current)) {
          arrivalsRef.current.push(n);
          setItems((prev) => merge(prev, [n]));
        }
        onArrive?.(n);
      }),
    [onArrive],
  );

  /** Changing the filter resets the list and the cursor. */
  const setFilter = (next: NotificationFilter) => {
    if (next === filterRef.current) return;
    filterRef.current = next;
    setFilterState(next);
    setItems([]);
    setHasMore(false);
    void loadFirst('initial');
  };

  const refresh = () => loadFirst('refresh');
  const retry = () => (error === 'more' ? loadMore(true) : loadFirst('initial'));

  /** Resolves false (and restores the item) when the delete failed. */
  const remove = async (id: string): Promise<boolean> => {
    const target = items.find((n) => n.id === id);
    if (!target) return true;
    deletedIdsRef.current.add(id);
    setItems((prev) => prev.filter((n) => n.id !== id));
    if (!target.read) setUnreadCount((c) => Math.max(0, c - 1));
    // Under "Semua" the loaded list is the whole feed head, so the next item is the new latest.
    const rest = items.filter((n) => n.id !== id);
    const nextLatest = rest[0] ? { createdAt: rest[0].createdAt, id: rest[0].id } : hasMore ? latest : null;
    try {
      await deleteNotification(id);
      if (latest?.id === id && filterRef.current === 'all') setLatest(nextLatest);
      return true;
    } catch {
      deletedIdsRef.current.delete(id);
      setItems((prev) => merge(prev, [target]));
      if (!target.read) setUnreadCount((c) => c + 1);
      return false;
    }
  };

  /** Deletes every notification (all filters) up to the newest one known. Resolves false on failure. */
  const clearAll = async (): Promise<boolean> => {
    const boundary = newer(latest, items[0] ?? null);
    if (!boundary || clearing) return true;
    const snapshot = { items, hasMore, cursor: cursorRef.current, unreadCount, latest };
    generationRef.current += 1; // drop any page still in flight
    inFlightRef.current = null;
    cursorRef.current = null;
    const survivors = items.filter((n) => compareFeed(n, boundary) < 0);
    setItems(survivors);
    setHasMore(false);
    setError(null);
    setLoading(null);
    setUnreadCount(survivors.filter((n) => !n.read).length);
    setClearing(true);
    try {
      await clearNotifications(boundary);
      setLatest(survivors[0] ? { createdAt: survivors[0].createdAt, id: survivors[0].id } : null);
      return true;
    } catch {
      cursorRef.current = snapshot.cursor;
      setItems((prev) => merge(prev, snapshot.items));
      setHasMore(snapshot.hasMore);
      setUnreadCount(snapshot.unreadCount);
      setLatest((prev) => newer(prev, snapshot.latest));
      return false;
    } finally {
      setClearing(false);
    }
  };

  const markRead = (id: string) => {
    const target = items.find((n) => n.id === id);
    if (!target || target.read) return;
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
    setUnreadCount((c) => Math.max(0, c - 1));
    void markNotificationRead(id);
  };

  return {
    filter,
    setFilter,
    items,
    hasMore,
    loading,
    error,
    unreadCount,
    /** False when the user has no notifications at all (any filter). */
    hasAny: latest !== null || items.length > 0,
    clearing,
    loadMore,
    refresh,
    retry,
    remove,
    clearAll,
    markRead,
  };
}
