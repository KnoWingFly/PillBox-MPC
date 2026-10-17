// Notification feed service: the ONLY place that reads, deletes or marks notifications.
// Today it works on the in-memory mock store in lib/api.ts. Hooking up the FastAPI backend means
// changing the bodies below; the hook and UI (src/hooks/use-notification-feed.ts) stay as they are.

import { getMockNotifications, setMockNotifications } from './api';
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

/** Set to true to test the optimistic-delete rollback against the mock. */
const MOCK_FAIL_DELETES = false;
/** Set to true to test the list error states (first page and "load more"). */
const MOCK_FAIL_PAGES = false;

function mockDelay(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 250 + Math.round(Math.random() * 150)));
}

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

/** True when `n` is at or after (older than or equal to) `boundary` in feed order. */
function isAtOrOlder(n: FeedPosition, boundary: FeedPosition): boolean {
  return compareFeed(n, boundary) >= 0;
}

export const NOTIFICATION_PAGE_SIZE = 20;

export type NotificationPage = {
  items: AppNotification[];
  /** Pass back as `cursor` for the next page; null when there are no older items. */
  nextCursor: FeedPosition | null;
  /** Unread count across ALL filters. */
  unreadCount: number;
  /** Newest notification of any type (null = the user has none). Bounds "Hapus semua". */
  latest: FeedPosition | null;
};

function positionOf(n: AppNotification): FeedPosition {
  return { createdAt: n.createdAt, id: n.id };
}

/**
 * One page of the feed, newest first, strictly older than `cursor` (keyset pagination, so items
 * arriving at the top never shift or duplicate later pages).
 * TODO(backend): GET /notifications?tab=<ALL|ON_TIME|LATE_MISSED|SYSTEM>&limit=20&cursor=<opaque>
 *   -> {"data": [...], "next_cursor": string|null, "unread_count": number,
 *       "latest": {"created_at": ISO8601, "id": uuid}|null}
 *   ordered by created_at DESC, id DESC. Only this function changes when the backend lands.
 */
export async function fetchNotificationPage({
  filter,
  cursor,
  limit = NOTIFICATION_PAGE_SIZE,
}: {
  filter: NotificationFilter;
  cursor: FeedPosition | null;
  limit?: number;
}): Promise<NotificationPage> {
  await mockDelay();
  if (MOCK_FAIL_PAGES) throw new Error('mock page failure');
  const all = [...getMockNotifications()].sort(compareFeed);
  const matching = all.filter((n) => matchesFilter(n, filter) && (!cursor || compareFeed(n, cursor) > 0));
  const items = matching.slice(0, limit);
  return {
    items,
    nextCursor: matching.length > limit ? positionOf(items[items.length - 1]) : null,
    unreadCount: all.filter((n) => !n.read).length,
    latest: all.length ? positionOf(all[0]) : null,
  };
}

/**
 * Permanently deletes one notification.
 * TODO(backend): DELETE /notifications/{id} -> 204. Treat 404 as success (already gone).
 * Deletes only the caller's row, never other caregivers' copies of a shared incident.
 */
export async function deleteNotification(id: string): Promise<void> {
  await mockDelay();
  if (MOCK_FAIL_DELETES) throw new Error('mock delete failure');
  setMockNotifications(getMockNotifications().filter((n) => n.id !== id));
}

/**
 * Permanently deletes every notification up to and including `upTo` (the newest one the user saw
 * when confirming), so anything that arrives after the confirmation survives.
 * TODO(backend): DELETE /notifications?tab=ALL&up_to_created_at=<ISO8601>&up_to_id=<uuid>
 *   -> 200 {"deleted": number}; only rows with (created_at, id) <= (up_to_created_at, up_to_id).
 */
export async function clearNotifications(upTo: FeedPosition): Promise<{ deleted: number }> {
  await mockDelay();
  if (MOCK_FAIL_DELETES) throw new Error('mock clear failure');
  const before = getMockNotifications();
  const kept = before.filter((n) => !isAtOrOlder(n, upTo));
  setMockNotifications(kept);
  return { deleted: before.length - kept.length };
}

/**
 * Marks one notification as read.
 * TODO(backend): PUT /notifications/{id}/read (exists on the backend branch).
 */
export async function markNotificationRead(id: string): Promise<void> {
  setMockNotifications(getMockNotifications().map((n) => (n.id === id ? { ...n, read: true } : n)));
}
