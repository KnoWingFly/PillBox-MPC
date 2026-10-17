import { ActivityIndicator, FlatList, Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';

import type { FeedError, FeedLoading } from '@/hooks/use-notification-feed';
import * as tokens from '@/theme/tokens';
import * as api from '@root/lib/api';
import { NOTIFICATION_FILTERS, type NotificationFilter } from '@root/lib/notifications';
import { formatJakartaTimestamp } from '@root/lib/schedule-time';
import type { AppNotification } from '@root/lib/types';

import { EMPTY_TEXT, formatRelative, notificationLook } from './helpers';
import { SwipeToDelete } from './swipe-to-delete';
import { Button, Chip, EmptyState, IconBadge, LoadErrorBox, ScreenHeader } from './ui';

function NotificationItem({
  notification,
  now,
  alarmBusy,
  onPress,
  onCall,
  onAlarm,
  onDelete,
}: {
  notification: AppNotification;
  now: number;
  alarmBusy: boolean;
  onPress: () => void;
  onCall: () => void;
  onAlarm: () => void;
  onDelete: () => void;
}) {
  const look = notificationLook(notification);
  // Only a missed dose needs the caregiver to act; a late dose was still taken.
  const needsAction = notification.type === 'missed';
  const when = `${formatJakartaTimestamp(notification.createdAt, now)} · ${formatRelative(notification.createdAt, now)}`;
  const slot = notification.slotId
    ? `Slot ${notification.slotId} · ${api.getSlotColumnLabel(notification.slotId)}`
    : null;

  // The card is a plain container: the tappable content and the action buttons are siblings, so
  // screen readers can reach each button (a button nested in a button is unreachable on iOS).
  return (
    <View
      className={`overflow-hidden rounded-3xl border ${
        notification.read ? 'border-line bg-surface-muted' : 'border-line bg-surface'
      }`}
      style={notification.read ? undefined : { boxShadow: tokens.shadow.card }}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${notification.read ? '' : 'Belum dibaca. '}${look.label}. ${notification.title}. ${
          notification.message
        } ${when}.`}
        accessibilityHint="Ketuk untuk menandai sudah dibaca. Geser ke kiri untuk menghapus."
        accessibilityActions={[{ name: 'delete', label: 'Hapus notifikasi' }]}
        onAccessibilityAction={(e) => {
          if (e.nativeEvent.actionName === 'delete') onDelete();
        }}
        onPress={onPress}
        className="flex-row gap-3 p-4 active:opacity-80">
        <IconBadge icon={look.icon} tone={look.tone} />
        <View className="flex-1 gap-1">
          <View className="flex-row items-start gap-2">
            <Text className={`flex-1 text-body text-ink ${notification.read ? 'font-semibold' : 'font-bold'}`}>
              {notification.title}
            </Text>
            {!notification.read && <View className="mt-2 h-2.5 w-2.5 rounded-full bg-missed-solid" />}
          </View>
          <Text className="text-body-sm text-ink">{notification.message}</Text>
          <Text className="text-body-sm text-ink-muted">
            {slot ? `${slot} · ` : ''}
            {when}
          </Text>
        </View>
      </Pressable>
      {needsAction && (
        <View className="flex-row gap-2 px-4 pb-4">
          <View className="flex-1">
            <Button label="Hubungi" icon="call-outline" variant="secondary" size="sm" onPress={onCall} accessibilityLabel="Hubungi lansia" />
          </View>
          <View className="flex-1">
            <Button label="Bunyikan Alarm" icon="alarm-outline" variant="danger" size="sm" loading={alarmBusy} onPress={onAlarm} />
          </View>
        </View>
      )}
    </View>
  );
}

/** Pinned under the title: filters and "Hapus semua". */
function FilterBar({
  filter,
  onFilter,
  canClear,
  clearing,
  onClearAll,
}: {
  filter: NotificationFilter;
  onFilter: (filter: NotificationFilter) => void;
  canClear: boolean;
  clearing: boolean;
  onClearAll: () => void;
}) {
  return (
    <View className="gap-2 bg-canvas pb-3 pt-1">
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerClassName="gap-2 px-4">
        {NOTIFICATION_FILTERS.map((f) => (
          <Chip key={f.key} label={f.label} selected={filter === f.key} onPress={() => onFilter(f.key)} />
        ))}
      </ScrollView>
      <View className="flex-row justify-end px-4">
        <Button
          label="Hapus semua"
          icon="trash-outline"
          variant="danger-soft"
          size="sm"
          loading={clearing}
          disabled={!canClear}
          onPress={onClearAll}
        />
      </View>
    </View>
  );
}

function ListFooter({
  filter,
  isEmpty,
  hasMore,
  loading,
  error,
  onRetry,
}: {
  filter: NotificationFilter;
  isEmpty: boolean;
  hasMore: boolean;
  loading: FeedLoading;
  error: FeedError;
  onRetry: () => void;
}) {
  if (loading === 'initial' || loading === 'more') {
    return (
      <View className="items-center py-6" accessibilityLabel="Memuat notifikasi">
        <ActivityIndicator color={tokens.colors.primary.DEFAULT} size="large" />
      </View>
    );
  }
  if (error) {
    return (
      <View className="px-4 pt-2">
        <LoadErrorBox
          text={`${error === 'initial' ? 'Gagal memuat notifikasi.' : 'Gagal memuat notifikasi berikutnya.'} Periksa koneksi lalu coba lagi.`}
          onRetry={onRetry}
        />
      </View>
    );
  }
  if (isEmpty) {
    const empty = EMPTY_TEXT[filter];
    return <EmptyState icon="notifications-off-outline" title={empty.title} text={empty.text} />;
  }
  if (!hasMore) {
    return <Text className="px-4 py-6 text-center text-body-sm text-ink-muted">Semua notifikasi sudah ditampilkan.</Text>;
  }
  return null;
}

type Row = { kind: 'title' } | { kind: 'filters' } | { kind: 'item'; notification: AppNotification };
const TITLE_ROW: Row = { kind: 'title' };
const FILTER_ROW: Row = { kind: 'filters' };

export function NotificationsTab({
  feed,
  now,
  alarmBusyId,
  refreshing,
  onRefresh,
  onMarkRead,
  onCall,
  onAlarm,
  onDelete,
  onClearAll,
}: {
  feed: {
    filter: NotificationFilter;
    setFilter: (f: NotificationFilter) => void;
    items: AppNotification[];
    hasMore: boolean;
    loading: FeedLoading;
    error: FeedError;
    unreadCount: number;
    hasAny: boolean;
    clearing: boolean;
    loadMore: () => Promise<void>;
    retry: () => Promise<void>;
  };
  now: number;
  alarmBusyId: string | null;
  refreshing: boolean;
  onRefresh: () => void;
  onMarkRead: (id: string) => void;
  onCall: (n: AppNotification) => void;
  onAlarm: (n: AppNotification) => void;
  onDelete: (n: AppNotification) => void;
  onClearAll: () => void;
}) {
  // Row 0 is the title (scrolls away), row 1 the filter bar (sticky), then the notifications.
  const rows: Row[] = [TITLE_ROW, FILTER_ROW, ...feed.items.map((n): Row => ({ kind: 'item', notification: n }))];

  const renderRow = ({ item }: { item: Row }) => {
    if (item.kind === 'title') {
      return (
        <View className="px-4 pb-2 pt-4">
          <ScreenHeader
            title="Notifikasi"
            subtitle={feed.unreadCount > 0 ? `${feed.unreadCount} belum dibaca` : 'Semua sudah dibaca'}
          />
        </View>
      );
    }
    if (item.kind === 'filters') {
      return (
        <FilterBar
          filter={feed.filter}
          onFilter={feed.setFilter}
          canClear={feed.hasAny}
          clearing={feed.clearing}
          onClearAll={onClearAll}
        />
      );
    }
    const n = item.notification;
    return (
      <View className="px-4 pb-3">
        <SwipeToDelete onDelete={() => onDelete(n)}>
          <NotificationItem
            notification={n}
            now={now}
            alarmBusy={alarmBusyId === n.id}
            onPress={() => onMarkRead(n.id)}
            onCall={() => onCall(n)}
            onAlarm={() => onAlarm(n)}
            onDelete={() => onDelete(n)}
          />
        </SwipeToDelete>
      </View>
    );
  };

  return (
    <FlatList
      data={rows}
      keyExtractor={(row) => (row.kind === 'item' ? row.notification.id : row.kind)}
      renderItem={renderRow}
      stickyHeaderIndices={[1]}
      onEndReached={() => void feed.loadMore()}
      onEndReachedThreshold={0.5}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          colors={[tokens.colors.primary.DEFAULT]}
          tintColor={tokens.colors.primary.DEFAULT}
        />
      }
      contentContainerClassName="pb-8"
      ListFooterComponent={
        <ListFooter
          filter={feed.filter}
          isEmpty={feed.items.length === 0}
          hasMore={feed.hasMore}
          loading={feed.loading}
          error={feed.error}
          onRetry={() => void feed.retry()}
        />
      }
    />
  );
}
