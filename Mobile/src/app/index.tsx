// Caregiver dashboard for the Smart Pillbox (test harness).
// Data comes from lib/api.ts: the FastAPI backend when EXPO_PUBLIC_PILLBOX_API_URL is set, else mock data.
//
// One screen with four sections (Beranda, Jadwal, Notifikasi, Perangkat) swapped by a bottom tab
// bar. State lives here so the sections share it (e.g. an unsaved schedule survives a tab switch).

import { useLocalSearchParams, useRouter } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, BackHandler, Linking, Modal, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppConfig } from '@/config';
import { ConnectPillboxScreen } from '@/components/pillbox/connect-card';
import { TopBar } from '@/components/pillbox/blocks';
import { PillboxListCard, RenamePillboxDialog } from '@/components/pillbox/device-list';
import { DeviceTab } from '@/components/pillbox/device-tab';
import { deviceLook, isDraftDirty, isSlotActive, notificationLook, pillboxNow, type ToastTone } from '@/components/pillbox/helpers';
import { HomeTab } from '@/components/pillbox/home-tab';
import { NotificationsTab, type DoseActionBusy } from '@/components/pillbox/notifications-tab';
import { ConfirmDialog, type ConfirmRequest } from '@/components/pillbox/dialog';
import { PinPrompt } from '@/components/pillbox/pin-prompt';
import { ScheduleSyncedSheet } from '@/components/pillbox/schedule-synced-sheet';
import { ServerBanner } from '@/components/pillbox/server-banner';
import { ScheduleTab } from '@/components/pillbox/schedule-tab';
import { SettingsTab } from '@/components/pillbox/settings-tab';
import { BackHeader } from '@/components/ui/back-header';
import { TabBar, type TabKey } from '@/components/pillbox/tab-bar';
import { makeToast, Toast, type ToastData } from '@/components/pillbox/toast';
import { LoadErrorBox } from '@/components/pillbox/ui';
import * as tokens from '@/theme/tokens';
import { useAuth } from '@/hooks/use-auth';
import { useBackendHealth } from '@/hooks/use-backend-health';
import { useDashboardInsights } from '@/hooks/use-dashboard-insights';
import { Strings } from '@/constants/strings';
import { useNotificationFeed } from '@/hooks/use-notification-feed';
import { usePillboxAlarm } from '@/hooks/use-pillbox-alarm';
import { usePolling } from '@/hooks/use-polling';
import { useToast } from '@/hooks/use-toast';
import { failMessage } from '@/lib/api/error-message';
import { perfLog, perfLoginStep } from '@/lib/perf';
import { DevicesProvider, useDevices } from '@root/context/devices-context';
import * as api from '@root/lib/api';
import { canEdit, type ConnectPillboxResult, type Pillbox } from '@root/lib/devices';
import { NOTIFICATION_DELETE_SUPPORTED } from '@root/lib/notifications';
import { findAllConflicts, timezoneLabel } from '@root/lib/schedule-time';
import type {
  AdherenceSummary,
  AppNotification,
  DeviceStatus,
  DoseEventType,
  NotificationAction,
  Slot,
  SlotId,
} from '@root/lib/types';

/** The active pillbox no longer exists for this account (unpaired here or by another caregiver). */
function pillboxGone(err: unknown): boolean {
  return err instanceof api.BackendError && (err.code === 'NO_DEVICE' || err.status === 404 || err.status === 403);
}

const D = Strings.dashboard;

const TAB_KEYS: readonly TabKey[] = ['home', 'schedule', 'notifications', 'device', 'settings'];
const isTabKey = (value: string | undefined): value is TabKey => TAB_KEYS.includes(value as TabKey);

/** Lookups ConnectPillboxScreen needs from the account's list (no extra request). */
function pairingLookups(devices: ReturnType<typeof useDevices>) {
  return {
    myDeviceIds: devices.all.map((p) => p.id),
    findExisting: (code: string) => {
      const found = devices.all.find((p) => p.code === code);
      return found ? { id: found.id, name: found.name, hidden: devices.hidden.some((h) => h.id === found.id) } : null;
    },
  };
}

/**
 * After pairing or joining: the new pillbox becomes active, which remounts the dashboard, so the
 * result toast is handed over through `onCarry`. `showToast` reports a list reload that failed.
 */
function useConnectedHandler(onCarry: (carry: Carry) => void, showToast: (text: string, tone: ToastTone) => void) {
  const devices = useDevices();
  return async (result: ConnectPillboxResult) => {
    const linked = result.joined ? D.joined : D.paired;
    const message = result.online === false ? makeToast(D.linkedOffline(linked), 'warning') : makeToast(linked, 'success');
    api.resubscribeRealtime();
    onCarry({ tab: 'home', toast: message });
    try {
      await devices.added(result.deviceId);
    } catch {
      showToast(D.linkedReloadList, 'warning');
    }
  };
}

/** What survives the remount when the active pillbox changes (the dashboard is keyed by it). */
type Carry = { tab?: TabKey; toast?: ToastData };

export default function PillboxScreen() {
  return (
    <DevicesProvider>
      <PillboxGate />
    </DevicesProvider>
  );
}

/**
 * Waits for the pillbox list, then mounts the dashboard keyed by the active pillbox: switching
 * pillboxes remounts it, so every tab, poll and in-flight request belongs to one pillbox only.
 */
function PillboxGate() {
  const devices = useDevices();
  // `/?tab=schedule&at=<ms>` opens a tab (e.g. "Atur Jadwal Obat Sekarang" after saving a profile);
  // `at` makes the same tab requested twice count as two requests.
  const params = useLocalSearchParams<{ tab?: string; at?: string }>();
  const requestedTab = isTabKey(params.tab) ? params.tab : null;
  const tabRequest = requestedTab ? { tab: requestedTab, id: params.at ?? requestedTab } : null;
  const [carriedTab, setCarriedTab] = useState<TabKey>(requestedTab ?? 'home');
  // Toasts that must outlive a remount (e.g. "dihapus" after removing the active pillbox) live here.
  const [carriedToast, setCarriedToast] = useState<ToastData | null>(null);
  const hideCarried = useCallback((id: number) => {
    setCarriedToast((current) => (current?.id === id ? null : current));
  }, []);
  const carry = useCallback((next: Carry) => {
    if (next.tab) setCarriedTab(next.tab);
    if (next.toast) setCarriedToast(next.toast);
  }, []);
  if (devices.pillboxes === null) {
    return (
      <SafeAreaView style={{ flex: 1 }} className="items-center justify-center gap-4 bg-canvas px-6">
        {devices.loadError ? (
          <LoadErrorBox
            text={`${D.listLoadError}${__DEV__ ? D.devServer(api.BASE_URL) : ''}`}
            onRetry={() => void devices.refresh()}
          />
        ) : (
          <ActivityIndicator color={tokens.colors.primary.DEFAULT} />
        )}
      </SafeAreaView>
    );
  }
  // Backend mode without a selected pillbox: only the pairing screen mounts, so no feed, poll or
  // socket runs for a dashboard that has nothing to show.
  const needsPairing = !api.USE_MOCK && devices.active === null;
  return (
    <>
      {needsPairing ? (
        <NeedsPairingScreen onCarry={carry} />
      ) : (
        <PillboxDashboard key={devices.active?.id ?? 'none'} initialTab={carriedTab} tabRequest={tabRequest} onCarry={carry} />
      )}
      {carriedToast && <Toast key={carriedToast.id} toast={carriedToast} onDone={hideCarried} />}
    </>
  );
}

/** Full-screen "Belum ada pillbox": pair or join one, or sign out. */
function NeedsPairingScreen({ onCarry }: { onCarry: (carry: Carry) => void }) {
  const devices = useDevices();
  const { signOut } = useAuth();
  const { showToast, toastNode } = useToast();
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const handleConnected = useConnectedHandler(onCarry, showToast);
  const { myDeviceIds, findExisting } = pairingLookups(devices);

  const runConfirm = async () => {
    if (!confirm || busy) return;
    setBusy(true);
    try {
      await confirm.onConfirm();
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  };

  return (
    <View className="flex-1 bg-canvas">
      <StatusBar style="dark" />
      <SafeAreaView style={{ flex: 1 }} edges={['top', 'left', 'right', 'bottom']}>
        <ConnectPillboxScreen
          onConnected={(r) => void handleConnected(r)}
          findExisting={findExisting}
          myDeviceIds={myDeviceIds}
          onUnhide={() => void devices.unhideAll()}
          hiddenCount={devices.hidden.length}
          onSignOut={() => setConfirm(signOutRequest(signOut))}
        />
      </SafeAreaView>
      <ConfirmDialog request={confirm} busy={busy} onConfirm={() => void runConfirm()} onCancel={() => setConfirm(null)} />
      {toastNode}
    </View>
  );
}

function signOutRequest(signOut: () => Promise<void>): ConfirmRequest {
  return {
    title: D.signOutTitle,
    message: D.signOutMessage,
    confirmLabel: D.signOutConfirm,
    tone: 'danger',
    icon: 'log-out-outline',
    onConfirm: signOut,
  };
}

function PillboxDashboard({
  initialTab,
  tabRequest,
  onCarry,
}: {
  initialTab: TabKey;
  /** A tab asked for through the route (see PillboxGate); applied once per request id. */
  tabRequest: { tab: TabKey; id: string } | null;
  onCarry: (carry: Carry) => void;
}) {
  const devices = useDevices();
  const [tab, setTab] = useState<TabKey>(initialTab);
  const [seenTabRequest, setSeenTabRequest] = useState(tabRequest?.id ?? null);
  if (tabRequest && tabRequest.id !== seenTabRequest) {
    setSeenTabRequest(tabRequest.id);
    setTab(tabRequest.tab);
  }
  const [now, setNow] = useState(() => Date.now());
  const [toast, setToast] = useState<ToastData | null>(null);

  const [device, setDevice] = useState<DeviceStatus | null>(null);
  const [connectionBusy, setConnectionBusy] = useState(false);
  const [dashboardError, setDashboardError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<Pillbox | null>(null);

  const [savedSlots, setSavedSlots] = useState<Slot[]>([]);
  const [draftSlots, setDraftSlots] = useState<Slot[]>([]);
  const [selectedSlotId, setSelectedSlotId] = useState<SlotId | null>(null);
  const [saving, setSaving] = useState(false);
  /** Schedule just saved to an online pillbox: shown in the success sheet. */
  const [syncedSlots, setSyncedSlots] = useState<Slot[] | null>(null);
  const [testing, setTesting] = useState(false);
  const pillboxAlarm = usePillboxAlarm();

  const [alarmBusyId, setAlarmBusyId] = useState<string | null>(null);
  const [doseActionBusy, setDoseActionBusy] = useState<DoseActionBusy>(null);
  // Missed-dose notification waiting for the device PIN ("Buka bilik sekarang").
  const [releaseTarget, setReleaseTarget] = useState<AppNotification | null>(null);
  // "Are you sure?" dialog (Alert.alert does nothing on web).
  const { user, signOut } = useAuth();
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  // Synchronous guard: a double tap reaches runConfirm twice before confirmBusy re-renders.
  const confirmRunning = useRef(false);
  const [adherence, setAdherence] = useState<AdherenceSummary | null>(null);
  // Every request the dashboard makes reports here; the banner shows while the server is unreachable.
  const health = useBackendHealth();
  const trackHealth = health.track;

  const router = useRouter();
  // Today's doses, weekly chart, elderly profile, clock and preferences; days follow the pillbox clock.
  const insights = useDashboardInsights(pillboxNow(device, now), true);
  const refreshDoses = insights.refreshDoses;
  const [remindBusy, setRemindBusy] = useState(false);
  const [calibrateOpen, setCalibrateOpen] = useState(false);
  const [calibrateBusy, setCalibrateBusy] = useState(false);

  const [simSlotId, setSimSlotId] = useState<SlotId | null>(null);
  const [minutesLate, setMinutesLate] = useState(25);
  const [simBusy, setSimBusy] = useState<DoseEventType | null>(null);
  const [seeding, setSeeding] = useState(false);

  const adherenceGen = useRef(0);
  const refreshAdherence = useCallback(() => {
    const generation = ++adherenceGen.current;
    trackHealth(api.getAdherenceSummary())
      .then((summary) => {
        if (generation === adherenceGen.current) setAdherence(summary);
      })
      .catch(() => undefined); // the card keeps its last value; health shows an outage
  }, [trackHealth]);

  // Several dose notifications in a burst (a backlog after reconnecting) refetch once, not per item.
  const doseRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshAfterDoseEvent = useCallback(() => {
    if (doseRefreshTimer.current) clearTimeout(doseRefreshTimer.current);
    doseRefreshTimer.current = setTimeout(() => {
      doseRefreshTimer.current = null;
      refreshAdherence();
      refreshDoses();
    }, AppConfig.insightRefetchDebounceMs);
  }, [refreshAdherence, refreshDoses]);
  useEffect(
    () => () => {
      if (doseRefreshTimer.current) clearTimeout(doseRefreshTimer.current);
    },
    [],
  );

  // New notifications trigger the banner; dose events also change adherence.
  const handleArrive = useCallback(
    (n: AppNotification) => {
      perfLog('iot_to_app', 'shown_on_screen', { notification_id: n.id });
      setToast(makeToast(n.slotId ? D.arrived(n.title, n.slotId) : n.title, notificationLook(n).toast));
      setNow(Date.now());
      if (n.type !== 'system') refreshAfterDoseEvent();
    },
    [refreshAfterDoseEvent],
  );
  const feed = useNotificationFeed({ onArrive: handleArrive });

  const showToast = (text: string, tone: ToastTone) => setToast(makeToast(text, tone));
  const hideToast = useCallback((id: number) => {
    setToast((current) => (current?.id === id ? null : current));
  }, []);

  // Status answers can arrive out of order (a slow poll after a push): only the newest is applied.
  const statusGen = useRef(0);

  // Initial load from the data layer. Pairing or switching pillboxes remounts the dashboard instead.
  useEffect(() => {
    let cancelled = false;
    const generation = ++statusGen.current;
    trackHealth(Promise.all([api.getDeviceStatus(), api.getSchedules()]))
      .then(([status, slots]) => {
        if (cancelled) return;
        setDashboardError(false);
        if (generation === statusGen.current) setDevice(status);
        setSavedSlots(slots);
        setDraftSlots(slots);
        perfLoginStep('first_screen_data_loaded');
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (pillboxGone(err)) {
          void devices.refresh(); // unpaired elsewhere (or by another caregiver): reload the list
          return;
        }
        setDashboardError(true);
        // An unreachable server is already explained by the banner.
        if (!api.isServerUnreachable(err)) setToast(makeToast(failMessage(D.deviceLoadFailed, err), 'error'));
      });
    refreshAdherence();
    return () => {
      cancelled = true;
    };
    // Runs once per mount (the dashboard is keyed by pillbox). `devices` is read only on failure;
    // re-running on its changes would refetch on every list poll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Backend mode: online/offline, battery and last sync change on the device side. The backend
  // pushes them when they change; this poll is the fallback (slow while the socket is live, paused
  // in the background).
  const refreshStatus = useCallback(() => {
    const generation = ++statusGen.current;
    return trackHealth(api.getDeviceStatus()).then(
      (status) => {
        if (generation === statusGen.current) setDevice(status);
      },
      (err: unknown) => {
        if (pillboxGone(err)) void devices.refresh();
      },
    );
    // `devices.refresh` is stable; `devices` itself changes on every list poll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trackHealth, devices.refresh]);
  usePolling(refreshStatus, api.USE_MOCK ? null : AppConfig.deviceStatusPollMs, {
    slowWhen: api.isRealtimeLive,
    slowIntervalMs: api.REALTIME_FALLBACK_POLL_MS,
  });

  useEffect(() => {
    if (api.USE_MOCK) return;
    // Stock changes on the pillbox (refill, a sachet taken) arrive with the same heartbeat as the
    // status, but are not part of the pushed status: fetch them on each push. Only the stock field
    // is touched, so unsaved schedule edits survive. One request at a time.
    let stockInFlight = false;
    const refreshStock = () => {
      if (stockInFlight) return;
      stockInFlight = true;
      api
        .getStock()
        .then((stock) => {
          const apply = (slots: Slot[]) => slots.map((s) => (stock[s.id] === undefined ? s : { ...s, stock: stock[s.id]! }));
          setSavedSlots(apply);
          setDraftSlots(apply);
        })
        .catch(() => undefined)
        .finally(() => {
          stockInFlight = false;
        });
    };
    // Pushed values are applied directly (and win over any poll still in flight); without them, refetch.
    const unsubscribe = api.subscribeToDeviceChanges((status) => {
      if (status) {
        statusGen.current += 1;
        setDevice((prev) => (prev ? { ...prev, ...status } : prev));
      } else void refreshStatus();
      refreshStock();
    });
    return unsubscribe;
  }, [refreshStatus]);

  // Keeps relative times ("5 menit lalu") and the pillbox day fresh. Deliberately slow: the clock
  // card in the PillBox tab ticks every second on its own, so the whole dashboard does not re-render.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), AppConfig.dashboardTickMs);
    return () => clearInterval(timer);
  }, []);

  // Android back: Jadwal returns to PillBox, other tabs to Beranda, before leaving the app.
  useEffect(() => {
    if (tab === 'home') return;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      setTab(tab === 'schedule' ? 'device' : 'home');
      return true;
    });
    return () => sub.remove();
  }, [tab]);

  const firstActiveSlot = savedSlots.find((s) => isSlotActive(s));
  const effectiveSimSlot =
    simSlotId && isSlotActive(savedSlots.find((s) => s.id === simSlotId)) ? simSlotId : (firstActiveSlot?.id ?? null);
  const draftDirty = isDraftDirty(draftSlots, savedSlots);
  // PEMANTAU sees the schedule read-only (the backend refuses their writes anyway).
  const canEditSchedule = api.USE_MOCK || canEdit(devices.active?.myRole ?? null);
  // While the server is unreachable the pillbox state is unknown, not "missed": the banner says so.
  const deviceTone = health.unreachable ? null : device ? deviceLook(device, now).tone : dashboardError ? 'missed' : null;
  const scheduleTzLabel = timezoneLabel(insights.clock?.timezone ?? AppConfig.fallbackTimezone);
  // Time of day as the pillbox sees it: doses are due and missed by this clock, not the phone's.
  const pillboxNowMs = pillboxNow(device, now);

  const openTab = (next: TabKey) => {
    setTab(next);
    if (next === 'home') {
      setNow(Date.now());
    }
  };

  /** Reloads device status + schedules (retry, pull to refresh). `keepDraft` leaves unsaved edits alone. */
  const loadDashboard = async (keepDraft: boolean) => {
    const generation = ++statusGen.current;
    try {
      const [status, slots] = await trackHealth(Promise.all([api.getDeviceStatus(), api.getSchedules()]));
      if (generation === statusGen.current) setDevice(status);
      setSavedSlots(slots);
      if (!keepDraft) setDraftSlots(slots);
      setDashboardError(false);
    } catch (err) {
      if (pillboxGone(err)) void devices.refresh();
      else setDashboardError(true);
    }
  };

  const finishConnect = useConnectedHandler(onCarry, showToast);
  const handleConnected = async (result: ConnectPillboxResult) => {
    setAddOpen(false);
    await finishConnect(result);
  };

  /** Switches the active pillbox; an unsaved schedule draft would be lost, so ask first. */
  const handleSelectPillbox = (pillbox: Pillbox) => {
    const go = () => {
      onCarry({ tab, toast: makeToast(D.showing(pillbox.name), 'info') });
      devices.select(pillbox.id);
    };
    if (!draftDirty) return go();
    setConfirmRequest({
      title: D.switchTitle,
      message: D.switchMessage,
      confirmLabel: D.switchConfirm,
      cancelLabel: D.switchCancel,
      tone: 'warning',
      icon: 'swap-horizontal',
      onConfirm: go,
    });
  };

  const handleRenamePillbox = async (name: string) => {
    const target = renameTarget;
    if (!target) return;
    const ok = await devices.rename(target.id, name);
    setRenameTarget(null);
    if (ok) {
      showToast(D.renamed, 'success');
      if (target.id === devices.active?.id) setDevice((prev) => (prev ? { ...prev, deviceName: name } : prev));
    } else showToast(D.renameFailed, 'error');
  };

  const handleRemovePillbox = (pillbox: Pillbox) => {
    setConfirmRequest({
      title: D.removeTitle(pillbox.name),
      message: D.removeMessage(pillbox.code, pillbox.elderlyName),
      confirmLabel: D.removeConfirm,
      tone: 'danger',
      icon: 'trash-outline',
      onConfirm: async () => {
        const wasActive = pillbox.id === devices.active?.id;
        // Removing the active pillbox remounts the dashboard: the result toast is handed over.
        if (wasActive) onCarry({ tab: 'device' });
        const result = await devices.remove(pillbox);
        const message = !result
          ? makeToast(D.removeFailed(pillbox.name), 'error')
          : result.notificationsFailed !== 0
            ? makeToast(D.removedPartly(pillbox.name), 'warning')
            : makeToast(D.removed(pillbox.name), 'success');
        if (wasActive && result) onCarry({ tab: 'device', toast: message });
        else setToast(message);
      },
    });
  };

  const handleHidePillbox = (pillbox: Pillbox) => {
    setConfirmRequest({
      title: D.hideTitle(pillbox.name),
      message: D.hideMessage(pillbox.myRole === 'ADMIN'),
      confirmLabel: D.hideConfirm,
      tone: 'warning',
      icon: 'eye-off-outline',
      onConfirm: async () => {
        if (pillbox.id === devices.active?.id) onCarry({ tab: 'device', toast: makeToast(D.hidden(pillbox.name), 'info') });
        if (!(await devices.hide(pillbox.id))) showToast(D.hideFailed, 'error');
      },
    });
  };

  const { myDeviceIds, findExisting } = pairingLookups(devices);

  const handleRefresh = async () => {
    setRefreshing(true);
    setNow(Date.now());
    refreshAdherence();
    insights.refreshAll();
    // An unsaved schedule draft is never thrown away by a refresh.
    await Promise.allSettled([feed.refresh(), loadDashboard(draftDirty), devices.refresh()]);
    setRefreshing(false);
  };

  const handleRetryDashboard = () => {
    setDashboardError(false);
    void loadDashboard(draftDirty);
  };

  const handleToggleConnection = async () => {
    if (!device) return;
    setConnectionBusy(true);
    try {
      setDevice(await api.setDeviceConnection(!device.online));
    } catch {
      showToast(D.connectionToggleFailed, 'error');
    } finally {
      setConnectionBusy(false);
    }
  };

  const handleSimulate = async (type: DoseEventType) => {
    if (!effectiveSimSlot) return;
    setSimBusy(type);
    try {
      // The resulting notification arrives through the feed subscription.
      await api.simulateDoseEvent({ slotId: effectiveSimSlot, type, minutesLate });
    } catch {
      showToast(D.simulateFailed, 'error');
    } finally {
      setSimBusy(null);
    }
  };

  const handleSeed = async () => {
    setSeeding(true);
    try {
      await api.seedMockHistory(api.MOCK_SEED_COUNT);
      await feed.refresh();
      refreshAdherence();
      insights.refreshDoses();
      showToast(D.seeded(api.MOCK_SEED_COUNT), 'success');
    } catch {
      showToast(D.seedFailed, 'error');
    } finally {
      setSeeding(false);
    }
  };

  const handleMarkAllRead = () => {
    feed.markAllRead();
  };

  const markRead = (id: string) => {
    feed.markRead(id);
  };

  const handleDelete = async (n: AppNotification) => {
    if (!(await feed.remove(n.id))) showToast(D.deleteFailed, 'error');
  };

  const runConfirm = async () => {
    if (!confirmRequest || confirmRunning.current) return;
    confirmRunning.current = true;
    setConfirmBusy(true);
    try {
      await confirmRequest.onConfirm();
    } catch (err) {
      // onConfirm handlers report their own failures; this catches the ones that throw anyway.
      showToast(failMessage(D.actionFailed, err), 'error');
    } finally {
      confirmRunning.current = false;
      setConfirmBusy(false);
      setConfirmRequest(null);
    }
  };

  const handleSignOut = () => setConfirmRequest(signOutRequest(signOut));

  const handleClearAll = () => {
    setConfirmRequest({
      title: D.clearAllTitle,
      message: D.clearAllMessage(devices.active?.name ?? null),
      confirmLabel: D.clearAllConfirm,
      tone: 'danger',
      icon: 'trash-outline',
      onConfirm: async () => {
        if (await feed.clearAll()) showToast(D.clearedAll, 'success');
        else showToast(D.deleteFailed, 'error');
      },
    });
  };

  /** The elderly's own number; null hides every "call" action (nothing else is ever dialed). */
  const elderPhone = insights.elderly?.contactPhone ?? null;
  const callElder = async () => {
    if (!elderPhone) return;
    try {
      await Linking.openURL(`tel:${elderPhone}`);
    } catch {
      showToast(D.callFailed, 'error');
    }
  };

  const handleCall = async (n: AppNotification) => {
    markRead(n.id);
    await callElder();
  };

  /** Rings the pillbox (optionally at one compartment). Resolves false when the command failed. */
  const ringAlarm = async (slotId: SlotId | null) => {
    try {
      await api.triggerAlarm(slotId);
      pillboxAlarm.started(AppConfig.alarmDurationSeconds);
      showToast(D.alarmRung(device?.deviceName ?? devices.active?.name ?? Strings.connect.nicknameDefault), 'success');
    } catch (err) {
      showToast(failMessage(D.alarmFailed, err), 'error');
    }
  };

  const handleAlarm = async (n: AppNotification) => {
    markRead(n.id);
    setAlarmBusyId(n.id);
    await ringAlarm(n.slotId);
    setAlarmBusyId(null);
  };

  const handleRemind = async (slotId: SlotId) => {
    setRemindBusy(true);
    await ringAlarm(slotId);
    setRemindBusy(false);
  };

  const handleCalibrate = async (pin: string) => {
    setCalibrateBusy(true);
    try {
      await insights.calibrate(pin);
      setCalibrateOpen(false);
      showToast(Strings.device.calibrated, 'success');
    } catch (err) {
      const wrongPin = err instanceof api.BackendError && err.code === 'DEVICE_PIN_INCORRECT';
      if (!wrongPin) setCalibrateOpen(false);
      showToast(wrongPin ? Strings.device.pinIncorrect : failMessage(Strings.device.calibrateFailed, err), 'error');
    } finally {
      setCalibrateBusy(false);
    }
  };

  const handleAutoSync = async (value: boolean) => {
    if (!(await insights.setAutoSync(value))) showToast(Strings.device.autoSyncFailed, 'error');
  };

  const handleTogglePreference = async (key: Parameters<typeof insights.togglePreference>[0], value: boolean) => {
    if (!(await insights.togglePreference(key, value))) showToast(Strings.settings.prefsFailed, 'error');
  };

  /** A late-dose action changed the dose: refresh what shows it. */
  const afterDoseAction = () => {
    void feed.refresh();
    refreshAdherence();
    insights.refreshDoses();
  };

  const confirmTaken = async (n: AppNotification) => {
    setDoseActionBusy({ id: n.id, action: 'CONFIRM_TAKEN' });
    try {
      await api.confirmDoseTaken(n.id);
      showToast(D.confirmedTaken, 'success');
      afterDoseAction();
    } catch (err) {
      showToast(failMessage(D.confirmTakenFailed, err), 'error');
    } finally {
      setDoseActionBusy(null);
    }
  };

  const handleDoseAction = (n: AppNotification, action: NotificationAction) => {
    markRead(n.id);
    if (action === 'LATE_RELEASE') {
      setReleaseTarget(n);
      return;
    }
    setConfirmRequest({
      title: D.takenTitle,
      message: D.takenMessage,
      confirmLabel: D.takenConfirm,
      tone: 'success',
      icon: 'checkmark-done-outline',
      onConfirm: () => confirmTaken(n),
    });
  };

  const handleRelease = async (pin: string) => {
    const n = releaseTarget;
    if (!n) return;
    setDoseActionBusy({ id: n.id, action: 'LATE_RELEASE' });
    try {
      const { releaseUntil } = await api.releaseMissedDose(n.id, pin);
      setReleaseTarget(null);
      const until = releaseUntil.slice(11, 16); // "HH:MM" of the pillbox's own local time (device timezone)
      showToast(D.released(n.slotId ?? '', until), 'success');
    } catch (err) {
      const wrongPin = err instanceof api.BackendError && err.code === 'DEVICE_PIN_INCORRECT';
      if (!wrongPin) setReleaseTarget(null);
      showToast(wrongPin ? Strings.device.pinIncorrect : failMessage(D.releaseFailed, err), 'error');
    } finally {
      setDoseActionBusy(null);
    }
  };

  const handleChangeSlot = (id: SlotId, patch: Partial<Slot>) => {
    setDraftSlots((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  };

  const handleDiscard = () => {
    setConfirmRequest({
      title: D.discardTitle,
      message: D.discardMessage,
      confirmLabel: D.discardConfirm,
      cancelLabel: D.discardCancel,
      tone: 'danger',
      icon: 'arrow-undo-outline',
      onConfirm: () => setDraftSlots(savedSlots),
    });
  };

  const handleStopAlarm = async () => {
    try {
      await pillboxAlarm.stop();
      showToast(Strings.alarm.stopped, 'success');
    } catch (err) {
      showToast(failMessage(Strings.alarm.stopFailed, err), 'error');
    }
  };
  const alarmControl = { ringing: pillboxAlarm.ringing, stopping: pillboxAlarm.stopping, onStop: handleStopAlarm };

  const handleTestSlot = async (id: SlotId) => {
    setTesting(true);
    try {
      await api.triggerTestSlot(id);
      pillboxAlarm.started(AppConfig.testAlarmDurationSeconds);
      showToast(D.testSent(id), 'success');
    } catch (err) {
      showToast(failMessage(D.testFailed, err), 'error');
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    // The button is disabled on conflicts; re-check in case state changed in between.
    if (!canEditSchedule || saving) return;
    if (findAllConflicts(draftSlots).size > 0) {
      showToast(D.saveConflicts, 'error');
      return;
    }
    setSaving(true);
    try {
      const saved = await api.saveSchedule(draftSlots);
      setSavedSlots(saved);
      setDraftSlots(saved);
      // The sheet waits for the pillbox to report the new config_version as applied (or says it
      // is waiting, e.g. while the pillbox is offline): "saved" is not "on the pillbox".
      setSyncedSlots(saved);
    } catch (err) {
      showToast(failMessage(D.saveFailed, err), 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <View className="flex-1 bg-canvas">
      <StatusBar style="dark" />
      <SafeAreaView style={{ flex: 1 }} edges={['top', 'left', 'right']}>
          <>
            <TopBar userName={user?.full_name ?? Strings.shell.caregiverFallback} online={!health.unreachable} />
            {health.unreachable && <ServerBanner onRetry={() => void handleRefresh()} retrying={refreshing} />}
            {tab === 'schedule' && <BackHeader title={Strings.tabs.backToDevice} onBack={() => openTab('device')} />}
            <View className="flex-1">
              {tab === 'home' && (
                <HomeTab
                  now={now}
                  pillboxNow={pillboxNowMs}
                  userName={user?.full_name ?? null}
                  pillbox={devices.active}
                  device={device}
                  deviceLoadError={dashboardError}
                  onRetryDevice={handleRetryDashboard}
                  adherence={adherence}
                  insights={insights}
                  unreadCount={feed.unreadCount}
                  remindBusy={remindBusy}
                  alarm={alarmControl}
                  refreshing={refreshing}
                  onRefresh={handleRefresh}
                  onOpenTab={openTab}
                  onAddElderly={api.USE_MOCK ? undefined : () => router.push('/elderly/new')}
                  onCall={elderPhone ? () => void callElder() : undefined}
                  onRemind={(slotId) => void handleRemind(slotId)}
                />
              )}
              {tab === 'schedule' && (
                <ScheduleTab
                  draft={draftSlots}
                  saved={savedSlots}
                  selectedId={selectedSlotId}
                  onSelect={(id) => setSelectedSlotId((current) => (current === id ? null : id))}
                  onChangeSlot={handleChangeSlot}
                  loadError={dashboardError}
                  onRetry={handleRetryDashboard}
                  now={pillboxNowMs}
                  timezoneLabel={scheduleTzLabel}
                  canEdit={canEditSchedule}
                  testing={testing}
                  alarm={alarmControl}
                  onTest={handleTestSlot}
                  saving={saving}
                  onSave={handleSave}
                  onDiscard={handleDiscard}
                />
              )}
              {tab === 'notifications' && (
                <NotificationsTab
                  feed={feed}
                  canDelete={NOTIFICATION_DELETE_SUPPORTED}
                  now={now}
                  heading={insights.elderly?.fullName ?? devices.active?.elderlyName ?? Strings.shell.elderlyFallback}
                  alarmBusyId={alarmBusyId}
                  alarm={alarmControl}
                  actionBusy={doseActionBusy}
                  onAction={handleDoseAction}
                  refreshing={refreshing}
                  onRefresh={handleRefresh}
                  onMarkRead={markRead}
                  onMarkAllRead={handleMarkAllRead}
                  onCall={elderPhone ? handleCall : undefined}
                  onAlarm={handleAlarm}
                  onDelete={handleDelete}
                  onClearAll={handleClearAll}
                />
              )}
              {tab === 'device' && (
                <DeviceTab
                  device={device}
                  pillboxes={devices.pillboxes ?? []}
                  activeId={devices.active?.id ?? null}
                  elderlyName={insights.elderly?.fullName ?? devices.active?.elderlyName ?? null}
                  clock={insights.clock}
                  canEditDevice={api.USE_MOCK || canEdit(devices.active?.myRole ?? null)}
                  connectionBusy={connectionBusy}
                  now={now}
                  loadError={dashboardError}
                  onRetry={handleRetryDashboard}
                  onToggleConnection={handleToggleConnection}
                  refreshing={refreshing}
                  onRefresh={handleRefresh}
                  onSelectPillbox={handleSelectPillbox}
                  onAdd={api.USE_MOCK ? undefined : () => setAddOpen(true)}
                  onCalibrate={() => setCalibrateOpen(true)}
                  onToggleAutoSync={(value) => void handleAutoSync(value)}
                  onOpenSchedule={() => openTab('schedule')}
                  pillboxList={
                    api.USE_MOCK ? null : (
                      <PillboxListCard
                        pillboxes={devices.pillboxes ?? []}
                        hiddenCount={devices.hidden.length}
                        activeId={devices.active?.id ?? null}
                        now={now}
                        onSelect={handleSelectPillbox}
                        onAdd={() => setAddOpen(true)}
                        onRename={setRenameTarget}
                        onRemove={handleRemovePillbox}
                        onHide={handleHidePillbox}
                        onUnhideAll={() => void devices.unhideAll()}
                      />
                    )
                  }
                  simulator={{
                    slots: savedSlots,
                    slotId: effectiveSimSlot,
                    onSelectSlot: setSimSlotId,
                    minutesLate,
                    onChangeMinutesLate: setMinutesLate,
                    busyType: simBusy,
                    onSimulate: handleSimulate,
                    seeding,
                    onSeed: handleSeed,
                  }}
                />
              )}
              {tab === 'settings' && (
                <SettingsTab
                  now={now}
                  pillboxNow={pillboxNowMs}
                  userName={user?.full_name ?? Strings.shell.caregiverFallback}
                  email={user?.email ?? null}
                  accountId={user?.id ?? null}
                  pillbox={devices.active}
                  elderly={insights.elderly}
                  device={device}
                  prefs={insights.prefs}
                  prefsError={insights.prefsError}
                  prefsBusy={insights.prefsBusy}
                  onTogglePreference={(key, value) => void handleTogglePreference(key, value)}
                  onRetryPrefs={insights.refreshPrefs}
                  onCallElder={() => void callElder()}
                  onOpenDevice={() => openTab('device')}
                  onAddElderly={api.USE_MOCK ? undefined : () => router.push('/elderly/new')}
                  onAddDevice={api.USE_MOCK ? undefined : () => setAddOpen(true)}
                  onSignOut={handleSignOut}
                />
              )}
            </View>
            <TabBar
              active={tab}
              onChange={openTab}
              badges={{
                notifications: feed.unreadCount,
                scheduleDirty: draftDirty,
                deviceTone: deviceTone === 'late' || deviceTone === 'missed' ? deviceTone : null,
              }}
            />
          </>
      </SafeAreaView>

      <PinPrompt
        visible={calibrateOpen}
        title={Strings.device.calibrateTitle}
        message={Strings.device.calibrateMessage}
        confirmLabel={Strings.device.calibrateConfirm}
        busy={calibrateBusy}
        onSubmit={(pin) => void handleCalibrate(pin)}
        onCancel={() => setCalibrateOpen(false)}
      />
      <PinPrompt
        visible={releaseTarget !== null}
        title={D.releaseTitle}
        message={D.releaseMessage(releaseTarget?.slotId ?? '')}
        confirmLabel={D.releaseConfirm}
        busy={doseActionBusy?.action === 'LATE_RELEASE'}
        onSubmit={(pin) => void handleRelease(pin)}
        onCancel={() => setReleaseTarget(null)}
      />
      <Modal visible={addOpen} animationType="slide" onRequestClose={() => setAddOpen(false)} presentationStyle="pageSheet">
        <SafeAreaView style={{ flex: 1 }} className="bg-canvas">
          <ConnectPillboxScreen
            onConnected={(r) => void handleConnected(r)}
            findExisting={findExisting}
            myDeviceIds={myDeviceIds}
            onUnhide={() => {
              void devices.unhideAll();
              setAddOpen(false);
            }}
            onCancel={() => setAddOpen(false)}
          />
        </SafeAreaView>
      </Modal>
      {renameTarget && (
        <RenamePillboxDialog pillbox={renameTarget} onSave={handleRenamePillbox} onCancel={() => setRenameTarget(null)} />
      )}
      <ScheduleSyncedSheet
        slots={syncedSlots}
        device={device}
        deviceName={device?.deviceName ?? devices.active?.name ?? Strings.connect.nicknameDefault}
        timezoneLabel={scheduleTzLabel}
        elderlyName={insights.elderly?.fullName ?? devices.active?.elderlyName ?? null}
        onHome={() => {
          setSyncedSlots(null);
          openTab('home');
        }}
        onClose={() => setSyncedSlots(null)}
      />
      <ConfirmDialog
        request={confirmRequest}
        busy={confirmBusy}
        onConfirm={() => void runConfirm()}
        onCancel={() => setConfirmRequest(null)}
      />
      {toast && <Toast key={toast.id} toast={toast} onDone={hideToast} />}
    </View>
  );
}
