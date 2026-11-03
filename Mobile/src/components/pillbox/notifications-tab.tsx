import { memo } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import type { FeedError, FeedLoading } from '@/hooks/use-notification-feed';
import * as tokens from '@/theme/tokens';
import * as api from '@root/lib/api';
import { NOTIFICATION_FILTERS, type NotificationFilter } from '@root/lib/notifications';
import { formatJakartaTimestamp } from '@root/lib/schedule-time';
import type { AppNotification, NotificationAction } from '@root/lib/types';

import { EMPTY_TEXT, formatRelative, notificationLook } from './helpers';
import { AlarmButton, type AlarmControl } from './alarm-button';
import { SwipeToDelete } from './swipe-to-delete';
import { CountBadge } from './blocks';
import { Button, Chip, EmptyState, Icon, IconBadge, LoadErrorBox, StatusPill, TONE, type Tone } from './ui';

/** Which late-dose action is running, for the spinner. */
export type DoseActionBusy = { id: string; action: NotificationAction } | null;

const N = Strings.notifications;

/** The small tag top-right of a card: "+18 Menit", "Sesuai Jadwal", "Kritis". */
function cornerTag(n: AppNotification): { label: string; tone: Tone } | null {
  if (n.type === 'late' && n.minutesLate) return { label: N.lateTag(n.minutesLate), tone: 'late' };
  if (n.type === 'on_time') return { label: N.onTimeTag, tone: 'ontime' };
  if (n.type === 'missed' || n.severity === 'critical') return { label: N.criticalTag, tone: 'missed' };
  return null;
}

const NotificationItem = memo(function NotificationItem({
  notification,
  heading,
  now,
  alarmBusy,
  alarm,
  actionBusy,
  onPress,
  onCall,
  onAlarm,
  onAction,
  onDelete,
}: {
  notification: AppNotification;
  /** Elderly name shown as the card heading. */
  heading: string;
  now: number;
  alarmBusy: boolean;
  alarm: AlarmControl;
  actionBusy: NotificationAction | null;
  onPress: (n: AppNotification) => void;
  onCall: (n: AppNotification) => void;
  onAlarm: (n: AppNotification) => void;
  onAction: (n: AppNotification, action: NotificationAction) => void;
  /** Omitted when deleting is not supported. */
  onDelete?: (n: AppNotification) => void;
}) {
  const look = notificationLook(notification);
  const tag = cornerTag(notification);
  // Only a missed dose needs the caregiver to act; a late dose was still taken.
  const needsAction = notification.type === 'missed';
  const actions = notification.actions ?? [];
  const canRelease = actions.includes('LATE_RELEASE');
  const canConfirm = actions.includes('CONFIRM_TAKEN');
  const when = `${formatJakartaTimestamp(notification.createdAt, now)} · ${formatRelative(notification.createdAt, now)}`;
  const slot = notification.slotId
    ? Strings.shell.slotLabel(
        notification.slotId,
        api.getSlotColumnLabel(notification.slotId),
        api.getSlotRowLabel(notification.slotId),
      )
    : null;
  const remove = onDelete ? () => onDelete(notification) : undefined;

  // The card is a plain container: the tappable content and the action buttons are siblings, so
  // screen readers can reach each button (a button nested in a button is unreachable on iOS).
  return (
    <View
      className={`overflow-hidden rounded-3xl border ${notification.read ? 'border-line bg-surface-muted' : 'border-line bg-surface'}`}
      style={notification.read ? undefined : { boxShadow: tokens.shadow.card }}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${notification.read ? '' : N.unreadPrefix}${look.label}. ${heading}. ${notification.title}. ${
          notification.message
        } ${when}.`}
        accessibilityHint={remove ? N.swipeHint : N.tapHint}
        accessibilityActions={remove ? [{ name: 'delete', label: N.deleteA11y(notification.title) }] : undefined}
        onAccessibilityAction={(e) => {
          if (e.nativeEvent.actionName === 'delete') remove?.();
        }}
        onPress={() => onPress(notification)}
        className="gap-3 p-4 active:opacity-80">
        <View className={`flex-row items-start gap-3 ${remove ? 'pr-9' : ''}`}>
          <IconBadge icon={look.icon} tone={look.tone} size="lg" />
          <View className="flex-1 gap-1">
            <View className="flex-row flex-wrap items-center gap-2">
              <StatusPill label={look.label} tone={look.tone} />
              <Text className="text-caption text-ink-muted">{formatRelative(notification.createdAt, now)}</Text>
              {!notification.read && <View className="h-2.5 w-2.5 rounded-full bg-missed-solid" />}
            </View>
            <Text className={`text-title text-ink ${notification.read ? 'font-semibold' : 'font-bold'}`}>{heading}</Text>
          </View>
          {tag && (
            <View className={`rounded-full px-2.5 py-1 ${TONE[tag.tone].soft}`}>
              <Text className={`text-caption font-bold ${TONE[tag.tone].fg}`}>{tag.label}</Text>
            </View>
          )}
        </View>
        {slot && (
          <View className={`self-start rounded-lg px-2 py-0.5 ${TONE[look.tone].soft}`}>
            <Text className={`text-caption font-bold ${TONE[look.tone].fg}`}>{slot}</Text>
          </View>
        )}
        <View className="gap-1">
          <Text className="text-body font-semibold text-ink">{notification.title}</Text>
          <Text className="text-body-sm text-ink">{notification.message}</Text>
          <Text className="text-caption text-ink-muted">{when}</Text>
        </View>
      </Pressable>
      {remove && (
        // A sibling of the card's Pressable (not nested), so screen readers reach it on its own.
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={N.deleteA11y(notification.title)}
          onPress={remove}
          hitSlop={8}
          className="absolute right-2 top-2 h-10 w-10 items-center justify-center rounded-full active:bg-canvas">
          <Icon name="trash-outline" size={20} color={tokens.colors.ink.muted} />
        </Pressable>
      )}
      {(needsAction || canRelease || canConfirm) && (
        <View className="gap-2 px-4 pb-4">
          <View>
            <Button label={N.callElder} icon="call-outline" variant="secondary" size="sm" onPress={() => onCall(notification)} />
          </View>
          {needsAction && (
            <View>
              <AlarmButton
                label={N.ringAlarm}
                icon="alarm-outline"
                variant="primary"
                size="sm"
                starting={alarmBusy}
                onStart={() => onAlarm(notification)}
                alarm={alarm}
              />
            </View>
          )}
          {canRelease && (
            <View>
              <Button
                label={N.release}
                icon="lock-open-outline"
                variant="warning"
                size="sm"
                loading={actionBusy === 'LATE_RELEASE'}
                disabled={actionBusy !== null}
                onPress={() => onAction(notification, 'LATE_RELEASE')}
              />
            </View>
          )}
          {canConfirm && (
            <View>
              <Button
                label={N.confirmTaken}
                icon="checkmark-done-outline"
                variant="success"
                size="sm"
                loading={actionBusy === 'CONFIRM_TAKEN'}
                disabled={actionBusy !== null}
                onPress={() => onAction(notification, 'CONFIRM_TAKEN')}
              />
            </View>
          )}
        </View>
      )}
    </View>
  );
});

/** Pinned under the title: filters, the "Pantauan Lansia Aktif" banner and "Hapus semua". */
function FilterBar({
  filter,
  onFilter,
  unreadCount,
  onMarkAllRead,
  canDelete,
  canClear,
  clearing,
  onClearAll,
}: {
  filter: NotificationFilter;
  onFilter: (filter: NotificationFilter) => void;
  unreadCount: number;
  onMarkAllRead: () => void;
  /** False while the backend cannot delete: the button is hidden. */
  canDelete: boolean;
  canClear: boolean;
  clearing: boolean;
  onClearAll: () => void;
}) {
  return (
    <View className="gap-3 bg-canvas pb-3 pt-1">
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerClassName="gap-2 px-4">
        {NOTIFICATION_FILTERS.map((f) => (
          <Chip key={f.key} label={f.label} selected={filter === f.key} onPress={() => onFilter(f.key)} />
        ))}
      </ScrollView>
      <View className="mx-4 gap-3 rounded-3xl bg-primary-light p-4">
        <View className="flex-row items-center gap-3">
          <IconBadge icon="notifications" tone="primary" size="sm" />
          <View className="flex-1">
            <Text className="text-body font-bold text-ink">{N.bannerTitle}</Text>
            <Text className="text-body-sm text-ink-muted">{N.bannerText(unreadCount)}</Text>
          </View>
        </View>
        {(unreadCount > 0 || canDelete) && (
          <View className="flex-row flex-wrap justify-end gap-2">
            {unreadCount > 0 && (
              <Button label={N.markAllRead} icon="checkmark-done-outline" variant="secondary" size="sm" onPress={onMarkAllRead} />
            )}
            {canDelete && (
              <Button
                label={N.clearAll}
                icon="trash-outline"
                variant="danger-soft"
                size="sm"
                loading={clearing}
                disabled={!canClear}
                onPress={onClearAll}
              />
            )}
          </View>
        )}
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
      <View className="items-center py-6" accessibilityLabel={N.loading}>
        <ActivityIndicator color={tokens.colors.primary.DEFAULT} size="large" />
      </View>
    );
  }
  if (error) {
    return (
      <View className="px-4 pt-2">
        <LoadErrorBox
          text={error === 'initial' ? N.loadError : N.loadMoreError}
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
    return <Text className="px-4 py-6 text-center text-body-sm text-ink-muted">{N.end}</Text>;
  }
  return null;
}

type Row = { kind: 'title' } | { kind: 'filters' } | { kind: 'item'; notification: AppNotification };
const TITLE_ROW: Row = { kind: 'title' };
const FILTER_ROW: Row = { kind: 'filters' };

export function NotificationsTab({
  feed,
  canDelete,
  now,
  alarmBusyId,
  alarm,
  actionBusy,
  refreshing,
  onRefresh,
  heading,
  onMarkRead,
  onMarkAllRead,
  onCall,
  onAlarm,
  onAction,
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
  /** False while the backend has no delete endpoint: swipe and "Hapus semua" are hidden. */
  canDelete: boolean;
  now: number;
  alarmBusyId: string | null;
  alarm: AlarmControl;
  actionBusy: DoseActionBusy;
  refreshing: boolean;
  onRefresh: () => void;
  /** Card heading: the active pillbox's elderly name. */
  heading: string;
  onMarkRead: (id: string) => void;
  onMarkAllRead: () => void;
  onCall: (n: AppNotification) => void;
  onAlarm: (n: AppNotification) => void;
  onAction: (n: AppNotification, action: NotificationAction) => void;
  onDelete: (n: AppNotification) => void;
  onClearAll: () => void;
}) {
  // Row 0 is the title (scrolls away), row 1 the filter bar (sticky), then the notifications.
  const rows: Row[] = [TITLE_ROW, FILTER_ROW, ...feed.items.map((n): Row => ({ kind: 'item', notification: n }))];

  const markReadOf = (n: AppNotification) => onMarkRead(n.id);

  const renderRow = ({ item }: { item: Row }) => {
    if (item.kind === 'title') {
      return (
        <View className="px-4 pb-2 pt-4">
          <View className="flex-row items-center gap-2" accessible accessibilityRole="header" accessibilityLabel={`${N.title}, ${N.unreadA11y(feed.unreadCount)}`}>
            <Text className="text-display font-bold tracking-tight text-ink">{N.title}</Text>
            <CountBadge count={feed.unreadCount} />
          </View>
        </View>
      );
    }
    if (item.kind === 'filters') {
      return (
        <FilterBar
          filter={feed.filter}
          onFilter={feed.setFilter}
          unreadCount={feed.unreadCount}
          onMarkAllRead={onMarkAllRead}
          canDelete={canDelete}
          canClear={feed.hasAny}
          clearing={feed.clearing}
          onClearAll={onClearAll}
        />
      );
    }
    const n = item.notification;
    const card = (
      <NotificationItem
        notification={n}
        heading={heading}
        now={now}
        alarmBusy={alarmBusyId === n.id}
        alarm={alarm}
        actionBusy={actionBusy?.id === n.id ? actionBusy.action : null}
        onPress={markReadOf}
        onCall={onCall}
        onAlarm={onAlarm}
        onAction={onAction}
        onDelete={canDelete ? onDelete : undefined}
      />
    );
    return (
      <View className="px-4 pb-3">
        {canDelete ? <SwipeToDelete onDelete={() => onDelete(n)}>{card}</SwipeToDelete> : card}
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
