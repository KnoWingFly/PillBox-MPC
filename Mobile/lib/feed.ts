// Pure notification-feed helpers (no app or native imports, so they can be unit tested in Node).

import type { AppNotification } from './types';

export type NotificationFilter = 'all' | 'on_time' | 'issues' | 'system';

export const NOTIFICATION_FILTERS: { key: NotificationFilter; label: string }[] = [
  { key: 'all', label: 'Semua' },
  { key: 'on_time', label: 'Tepat Waktu' },
  { key: 'issues', label: 'Terlambat & Terlewat' },
  { key: 'system', label: 'Sistem' },
];

/** Position of a notification in the feed order (newest first). Used as pagination cursor and delete boundary. */
export type FeedPosition = { createdAt: number; id: string };

/**
 * Opaque "where the next page starts". The mock uses `position` (keyset); the backend's
 * GET /notifications only has page/limit, so it uses `offset` (rows of the server query consumed).
 */
export type FeedCursor = { position: FeedPosition | null; offset: number };

export function matchesFilter(n: AppNotification, filter: NotificationFilter): boolean {
  switch (filter) {
    case 'on_time':
      return n.type === 'on_time';
    case 'issues':
      return n.type === 'late' || n.type === 'missed';
    case 'system':
      return n.type === 'system';
    case 'all':
      return true;
  }
}

/** Feed order: createdAt desc, then id desc. Negative when `a` comes first. */
export function compareFeed(a: FeedPosition, b: FeedPosition): number {
  if (a.createdAt !== b.createdAt) return b.createdAt - a.createdAt;
  return a.id < b.id ? 1 : a.id > b.id ? -1 : 0;
}

export function positionOf(n: AppNotification): FeedPosition {
  return { createdAt: n.createdAt, id: n.id };
}

export type RawPage = { items: AppNotification[]; total: number; unreadCount: number };

/**
 * Builds one feed page on top of an offset-paginated server query (page numbers start at 1).
 * With a `match` filter (for filters the server cannot apply) it keeps reading server pages until
 * it has `limit` matching items or the query is exhausted, so a page is never empty while more
 * rows exist (an empty page would stall onEndReached).
 */
export async function pageFromOffsets({
  fetchRaw,
  pageSize,
  limit,
  cursor,
  match,
}: {
  fetchRaw: (page: number, pageSize: number) => Promise<RawPage>;
  /** Server page size; `cursor.offset` is always a multiple of it. */
  pageSize: number;
  limit: number;
  cursor: FeedCursor | null;
  match?: (n: AppNotification) => boolean;
}): Promise<{ items: AppNotification[]; nextCursor: FeedCursor | null; unreadCount: number; first: AppNotification | null }> {
  let offset = cursor?.offset ?? 0;
  const items: AppNotification[] = [];
  let unreadCount = 0;
  let first: AppNotification | null = null;
  let total = Infinity;
  while (offset < total && items.length < limit) {
    const raw = await fetchRaw(offset / pageSize + 1, pageSize);
    if (offset === 0) first = raw.items[0] ?? null;
    total = raw.total;
    unreadCount = raw.unreadCount;
    offset += pageSize;
    items.push(...(match ? raw.items.filter(match) : raw.items));
    if (raw.items.length < pageSize) total = Math.min(total, offset); // short page = last page
  }
  return {
    items,
    nextCursor: offset < total ? { position: items.length ? positionOf(items[items.length - 1]) : null, offset } : null,
    unreadCount,
    first,
  };
}
