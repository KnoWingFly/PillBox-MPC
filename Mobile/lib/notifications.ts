// Notification feed service: the ONLY place that reads, deletes or marks notifications.
// Mock mode works on the in-memory store in lib/api.ts; backend mode calls the FastAPI backend.
// The hook and UI (src/hooks/use-notification-feed.ts) are the same for both.

import {
  fetchBackendNotifications,
  getMockNotifications,
  markBackendNotificationRead,
  setMockNotifications,
  USE_MOCK,
  type BackendFeedTab,
} from './api';
import {
  compareFeed,
  matchesFilter,
  pageFromOffsets,
  positionOf,
  type FeedCursor,
  type FeedPosition,
  type NotificationFilter,
} from './feed';
import type { AppNotification } from './types';

export {
  compareFeed,
  matchesFilter,
  NOTIFICATION_FILTERS,
  type FeedCursor,
  type FeedPosition,
  type NotificationFilter,
} from './feed';

export const NOTIFICATION_PAGE_SIZE = 20;

/**
 * False while the backend has no delete endpoint: the UI then hides "Hapus semua" and
 * swipe-to-delete instead of offering an action that always fails.
 * TODO(backend): set to true once DELETE /notifications/{id} and DELETE /notifications exist.
 */
export const NOTIFICATION_DELETE_SUPPORTED = USE_MOCK;

/** Set to true to test the optimistic-delete rollback against the mock. */
const MOCK_FAIL_DELETES = false;
/** Set to true to test the list error states (first page and "load more"). */
const MOCK_FAIL_PAGES = false;
/**
 * Server rows read per request when the app filters on the phone ("Tepat Waktu", "Sistem" have
 * no backend tab). The backend caps limit at 100 (Backend/app/core/config.py max_page_limit).
 */
const BACKEND_SCAN_PAGE = 100;

function mockDelay(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 250 + Math.round(Math.random() * 150)));
}

export type NotificationPage = {
  items: AppNotification[];
  /** Pass back as `cursor` for the next page; null when there are no older items. */
  nextCursor: FeedCursor | null;
  /** Unread count across ALL filters. */
  unreadCount: number;
  /** Newest notification of any type when known (null = unknown or none). Bounds "Hapus semua". */
  latest: FeedPosition | null;
};

/** True when `n` is at or after (older than or equal to) `boundary` in feed order. */
function isAtOrOlder(n: FeedPosition, boundary: FeedPosition): boolean {
  return compareFeed(n, boundary) >= 0;
}

async function fetchMockPage(filter: NotificationFilter, cursor: FeedCursor | null, limit: number): Promise<NotificationPage> {
  await mockDelay();
  if (MOCK_FAIL_PAGES) throw new Error('mock page failure');
  const after = cursor?.position ?? null;
  const all = [...getMockNotifications()].sort(compareFeed);
  const matching = all.filter((n) => matchesFilter(n, filter) && (!after || compareFeed(n, after) > 0));
  const items = matching.slice(0, limit);
  return {
    items,
    nextCursor: matching.length > limit ? { position: positionOf(items[items.length - 1]), offset: 0 } : null,
    unreadCount: all.filter((n) => !n.read).length,
    latest: all.length ? positionOf(all[0]) : null,
  };
}

/**
 * Backend: GET /notifications?tab&page&limit (offset pagination, newest first).
 * "Semua" and "Terlambat & Terlewat" map to the ALL and LATE_MISSED tabs. Note that LATE_MISSED
 * only lists unresolved incidents. "Tepat Waktu" and "Sistem" have no tab yet, so they read ALL
 * and filter on the phone.
 * TODO(backend): ON_TIME and SYSTEM tabs, and cursor pagination (see the handoff list).
 */
async function fetchBackendPage(filter: NotificationFilter, cursor: FeedCursor | null, limit: number): Promise<NotificationPage> {
  const tab: BackendFeedTab = filter === 'issues' ? 'LATE_MISSED' : 'ALL';
  const serverFilters = filter === 'all' || filter === 'issues';
  const page = await pageFromOffsets({
    fetchRaw: (pageNumber, pageSize) => fetchBackendNotifications(tab, pageNumber, pageSize),
    pageSize: serverFilters ? limit : BACKEND_SCAN_PAGE,
    limit,
    cursor,
    match: serverFilters ? undefined : (n) => matchesFilter(n, filter),
  });
  return {
    items: page.items,
    nextCursor: page.nextCursor,
    unreadCount: page.unreadCount,
    // The first page of the ALL tab starts with the newest notification of any type.
    latest: tab === 'ALL' && page.first ? positionOf(page.first) : null,
  };
}

/**
 * One page of the feed, newest first, starting after `cursor`. The hook treats the cursor as opaque.
 */
export function fetchNotificationPage({
  filter,
  cursor,
  limit = NOTIFICATION_PAGE_SIZE,
}: {
  filter: NotificationFilter;
  cursor: FeedCursor | null;
  limit?: number;
}): Promise<NotificationPage> {
  return USE_MOCK ? fetchMockPage(filter, cursor, limit) : fetchBackendPage(filter, cursor, limit);
}

/**
 * Permanently deletes one notification.
 * TODO(backend): DELETE /notifications/{id} -> 204. Treat 404 as success (already gone).
 * Deletes only the caller's row, never other caregivers' copies of a shared incident.
 */
export async function deleteNotification(id: string): Promise<void> {
  if (!NOTIFICATION_DELETE_SUPPORTED) throw new Error('Deleting notifications is not supported by the backend yet');
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
  if (!NOTIFICATION_DELETE_SUPPORTED) throw new Error('Deleting notifications is not supported by the backend yet');
  await mockDelay();
  if (MOCK_FAIL_DELETES) throw new Error('mock clear failure');
  const before = getMockNotifications();
  const kept = before.filter((n) => !isAtOrOlder(n, upTo));
  setMockNotifications(kept);
  return { deleted: before.length - kept.length };
}

/** Marks one notification as read. Backend: PUT /notifications/{id}/read. */
export async function markNotificationRead(id: string): Promise<void> {
  if (!USE_MOCK) {
    await markBackendNotificationRead(id);
    return;
  }
  setMockNotifications(getMockNotifications().map((n) => (n.id === id ? { ...n, read: true } : n)));
}
