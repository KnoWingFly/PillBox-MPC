// Caregiver dashboard for the Smart Pillbox (test harness).
// Data comes from lib/api.ts: the FastAPI backend when EXPO_PUBLIC_PILLBOX_API_URL is set, else mock data.
//
// One screen with four sections (Beranda, Jadwal, Notifikasi, Perangkat) swapped by a bottom tab
// bar. State lives here so the sections share it (e.g. an unsaved schedule survives a tab switch).

import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useState } from 'react';
import { BackHandler, Linking, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppConfig } from '@/config';
import { ConnectPillboxScreen } from '@/components/pillbox/connect-card';
import { DeviceTab } from '@/components/pillbox/device-tab';
import { deviceLook, isDraftDirty, isSlotActive, notificationLook, pillboxNow, type ToastTone } from '@/components/pillbox/helpers';
import { HomeTab } from '@/components/pillbox/home-tab';
import { NotificationsTab, type DoseActionBusy } from '@/components/pillbox/notifications-tab';
import { ConfirmDialog, type ConfirmRequest } from '@/components/pillbox/dialog';
import { PinPrompt } from '@/components/pillbox/pin-prompt';
import { ScheduleTab } from '@/components/pillbox/schedule-tab';
import { TabBar, type TabKey } from '@/components/pillbox/tab-bar';
import { makeToast, Toast, type ToastData } from '@/components/pillbox/toast';
import { useNotificationFeed } from '@/hooks/use-notification-feed';
import { perfLog, perfLoginStep } from '@/lib/perf';
import * as api from '@root/lib/api';
import { fetchNotificationPage, NOTIFICATION_DELETE_SUPPORTED } from '@root/lib/notifications';
import { findAllConflicts } from '@root/lib/schedule-time';
import type {
  AdherenceSummary,
  AppNotification,
  DeviceStatus,
  DoseEventType,
  NotificationAction,
  Slot,
  SlotId,
} from '@root/lib/types';

const RECENT_COUNT = 3;

/** "Gagal …" plus the backend's own message when there is one (e.g. "Device is offline"). */
function failMessage(prefix: string, err: unknown): string {
  return err instanceof api.BackendError ? `${prefix}: ${err.message}` : prefix;
}

export default function PillboxDashboard() {
  const [tab, setTab] = useState<TabKey>('home');
  const [now, setNow] = useState(() => Date.now());
  const [toast, setToast] = useState<ToastData | null>(null);

  const [device, setDevice] = useState<DeviceStatus | null>(null);
  const [connectionBusy, setConnectionBusy] = useState(false);
  const [dashboardError, setDashboardError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  // Backend mode only: the caregiver has no paired pillbox yet.
  const [needsPairing, setNeedsPairing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const [savedSlots, setSavedSlots] = useState<Slot[]>([]);
  const [draftSlots, setDraftSlots] = useState<Slot[]>([]);
  const [selectedSlotId, setSelectedSlotId] = useState<SlotId | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const [alarmBusyId, setAlarmBusyId] = useState<string | null>(null);
  const [doseActionBusy, setDoseActionBusy] = useState<DoseActionBusy>(null);
  // Missed-dose notification waiting for the device PIN ("Buka bilik sekarang").
  const [releaseTarget, setReleaseTarget] = useState<AppNotification | null>(null);
  // "Are you sure?" dialog (Alert.alert does nothing on web).
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [adherence, setAdherence] = useState<AdherenceSummary | null>(null);
  const [recent, setRecent] = useState<AppNotification[]>([]);

  const [simSlotId, setSimSlotId] = useState<SlotId | null>(null);
  const [minutesLate, setMinutesLate] = useState(25);
  const [simBusy, setSimBusy] = useState<DoseEventType | null>(null);
  const [seeding, setSeeding] = useState(false);

  const refreshAdherence = useCallback(() => {
    api
      .getAdherenceSummary()
      .then(setAdherence)
      .catch(() => {});
  }, []);

  /** The few newest notifications (any type) shown on Beranda. */
  const refreshRecent = useCallback(() => {
    fetchNotificationPage({ filter: 'all', cursor: null, limit: RECENT_COUNT })
      .then((page) => setRecent(page.items))
      .catch(() => {});
  }, []);

  // New notifications trigger the banner; dose events also change adherence.
  const handleArrive = useCallback(
    (n: AppNotification) => {
      perfLog('iot_to_app', 'shown_on_screen', { notification_id: n.id });
      setToast(makeToast(n.slotId ? `${n.title} · ${n.slotId}` : n.title, notificationLook(n).toast));
      setNow(Date.now());
      refreshRecent();
      if (n.type !== 'system') refreshAdherence();
    },
    [refreshAdherence, refreshRecent],
  );
  const feed = useNotificationFeed({ onArrive: handleArrive });

  const showToast = (text: string, tone: ToastTone) => setToast(makeToast(text, tone));
  const hideToast = useCallback((id: number) => {
    setToast((current) => (current?.id === id ? null : current));
  }, []);

  // Initial load from the data layer; runs again after pairing a pillbox (reloadKey).
  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getDeviceStatus(), api.getSchedules()])
      .then(([status, slots]) => {
        if (cancelled) return;
        setNeedsPairing(false);
        setDashboardError(false);
        setDevice(status);
        setSavedSlots(slots);
        setDraftSlots(slots);
        perfLoginStep('first_screen_data_loaded');
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof api.BackendError && err.code === 'NO_DEVICE') {
          setNeedsPairing(true);
          return;
        }
        setDashboardError(true);
        setToast(makeToast(failMessage('Gagal memuat data perangkat', err), 'error'));
      });
    api
      .getAdherenceSummary()
      .then((summary) => {
        if (!cancelled) setAdherence(summary);
      })
      .catch(() => {});
    fetchNotificationPage({ filter: 'all', cursor: null, limit: RECENT_COUNT })
      .then((page) => {
        if (!cancelled) setRecent(page.items);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  // Backend mode: online/offline, battery and last sync change on the device side. The backend
  // pushes a hint when they change; the interval is the fallback when the socket is down.
  useEffect(() => {
    if (api.USE_MOCK || needsPairing) return;
    const refresh = () => {
      api.getDeviceStatus().then(setDevice).catch(() => undefined);
    };
    const timer = setInterval(refresh, AppConfig.deviceStatusPollMs);
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
    // Pushed values are applied directly; without them, refetch.
    const unsubscribe = api.subscribeToDeviceChanges((status) => {
      if (status) setDevice((prev) => (prev ? { ...prev, ...status } : prev));
      else refresh();
      refreshStock();
    });
    return () => {
      clearInterval(timer);
      unsubscribe();
    };
  }, [needsPairing]);

  // Keeps relative times ("5 menit lalu") fresh; every second while the pillbox clock runs fast
  // (emulator at 10x / 60x), so "next dose" keeps up with it.
  const clockSpeed = device?.clock?.speed ?? 1;
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), clockSpeed > 1 ? 1_000 : 30_000);
    return () => clearInterval(timer);
  }, [clockSpeed]);

  // Android back: return to Beranda before leaving the app.
  useEffect(() => {
    if (tab === 'home') return;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      setTab('home');
      return true;
    });
    return () => sub.remove();
  }, [tab]);

  const firstActiveSlot = savedSlots.find((s) => isSlotActive(s));
  const effectiveSimSlot =
    simSlotId && isSlotActive(savedSlots.find((s) => s.id === simSlotId)) ? simSlotId : (firstActiveSlot?.id ?? null);
  const draftDirty = isDraftDirty(draftSlots, savedSlots);
  const deviceTone = device ? deviceLook(device, now).tone : dashboardError ? 'missed' : null;
  // Time of day as the pillbox sees it: doses are due and missed by this clock, not the phone's.
  const pillboxNowMs = pillboxNow(device, now);

  const openTab = (next: TabKey) => {
    setTab(next);
    if (next === 'home') {
      setNow(Date.now());
      refreshRecent();
    }
  };

  /** Reloads device status + schedules (retry, pull to refresh). `keepDraft` leaves unsaved edits alone. */
  const loadDashboard = async (keepDraft: boolean) => {
    try {
      const [status, slots] = await Promise.all([api.getDeviceStatus(), api.getSchedules()]);
      setDevice(status);
      setSavedSlots(slots);
      if (!keepDraft) setDraftSlots(slots);
      setDashboardError(false);
    } catch (err) {
      if (err instanceof api.BackendError && err.code === 'NO_DEVICE') setNeedsPairing(true);
      else setDashboardError(true);
    }
  };

  const handleConnected = (result: api.ConnectPillboxResult) => {
    showToast(result.joined ? 'Bergabung ke pillbox (mode pemantau)' : 'Pillbox berhasil dihubungkan', 'success');
    api.resubscribeRealtime();
    setTab('home');
    setReloadKey((k) => k + 1);
    void feed.refresh();
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    setNow(Date.now());
    refreshAdherence();
    refreshRecent();
    // An unsaved schedule draft is never thrown away by a refresh.
    await Promise.allSettled([feed.refresh(), loadDashboard(draftDirty)]);
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
      showToast('Gagal mengubah status koneksi', 'error');
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
      showToast('Gagal mengirim kejadian simulasi', 'error');
    } finally {
      setSimBusy(null);
    }
  };

  const handleSeed = async () => {
    setSeeding(true);
    try {
      await api.seedMockHistory(45);
      await feed.refresh();
      refreshAdherence();
      refreshRecent();
      showToast('45 riwayat contoh ditambahkan', 'success');
    } catch {
      showToast('Gagal menambah riwayat contoh', 'error');
    } finally {
      setSeeding(false);
    }
  };

  const markRead = (id: string) => {
    feed.markRead(id);
    setRecent((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
  };

  const handleDelete = async (n: AppNotification) => {
    if (await feed.remove(n.id)) refreshRecent();
    else showToast('Gagal menghapus. Notifikasi dikembalikan.', 'error');
  };

  const runConfirm = async () => {
    if (!confirmRequest) return;
    setConfirmBusy(true);
    try {
      await confirmRequest.onConfirm();
    } finally {
      setConfirmBusy(false);
      setConfirmRequest(null);
    }
  };

  const handleClearAll = () => {
    setConfirmRequest({
      title: 'Hapus semua notifikasi?',
      message:
        'Semua notifikasi, termasuk yang tidak tampil di filter ini, akan dihapus permanen dan tidak bisa dikembalikan. ' +
        'Notifikasi pengasuh lain tidak ikut terhapus.',
      confirmLabel: 'Hapus Semua',
      tone: 'danger',
      icon: 'trash-outline',
      onConfirm: async () => {
        if (await feed.clearAll()) {
          refreshRecent();
          showToast('Semua notifikasi dihapus', 'success');
        } else {
          showToast('Gagal menghapus. Notifikasi dikembalikan.', 'error');
        }
      },
    });
  };

  const handleCall = async (n: AppNotification) => {
    markRead(n.id);
    try {
      await Linking.openURL(`tel:${AppConfig.elderPhone}`);
    } catch {
      showToast('Tidak dapat membuka aplikasi telepon', 'error');
    }
  };

  const handleAlarm = async (n: AppNotification) => {
    markRead(n.id);
    setAlarmBusyId(n.id);
    try {
      await api.triggerAlarm(n.slotId);
      showToast(`Alarm dibunyikan di ${device?.deviceName ?? 'Pillbox'}`, 'success');
    } catch (err) {
      // e.g. "Device is offline; the command was not sent" from the backend
      showToast(failMessage('Gagal membunyikan alarm', err), 'error');
    } finally {
      setAlarmBusyId(null);
    }
  };

  /** A late-dose action changed the dose: refresh what shows it. */
  const afterDoseAction = () => {
    void feed.refresh();
    refreshRecent();
    refreshAdherence();
  };

  const confirmTaken = async (n: AppNotification) => {
    setDoseActionBusy({ id: n.id, action: 'CONFIRM_TAKEN' });
    try {
      await api.confirmDoseTaken(n.id);
      showToast('Dicatat: obat diminum terlambat', 'success');
      afterDoseAction();
    } catch (err) {
      // e.g. "Sudah lewat batas aman (pukul 10:00) ... Jangan diminum, tunggu jadwal berikutnya."
      showToast(failMessage('Gagal mencatat', err), 'error');
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
      title: 'Obat sudah diminum?',
      message:
        'Dosis ini akan dicatat sebagai diminum terlambat dan peringatannya ditutup. Pastikan lansia benar-benar sudah meminumnya.',
      confirmLabel: 'Ya, Sudah Diminum',
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
      const until = releaseUntil.slice(11, 16); // pillbox clock, already in WIB
      showToast(`Bilik ${n.slotId ?? ''} dibuka sampai ${until}. Minta lansia mengambil obatnya.`, 'success');
    } catch (err) {
      if (!(err instanceof api.BackendError) || err.code !== 'DEVICE_PIN_INCORRECT') setReleaseTarget(null);
      showToast(
        err instanceof api.BackendError && err.code === 'DEVICE_PIN_INCORRECT' ? 'PIN salah' : failMessage('Gagal membuka bilik', err),
        'error',
      );
    } finally {
      setDoseActionBusy(null);
    }
  };

  const handleChangeSlot = (id: SlotId, patch: Partial<Slot>) => {
    setDraftSlots((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  };

  const handleDiscard = () => {
    setConfirmRequest({
      title: 'Batalkan perubahan?',
      message: 'Perubahan jadwal yang belum disimpan akan hilang. Jadwal kembali seperti yang tersimpan di Pillbox.',
      confirmLabel: 'Batalkan Perubahan',
      cancelLabel: 'Tidak',
      tone: 'danger',
      icon: 'arrow-undo-outline',
      onConfirm: () => setDraftSlots(savedSlots),
    });
  };

  const handleTestSlot = async (id: SlotId) => {
    setTesting(true);
    try {
      await api.triggerTestSlot(id);
      showToast(`Tes pengingat dikirim ke slot ${id}`, 'success');
    } catch (err) {
      showToast(failMessage('Gagal mengirim tes pengingat', err), 'error');
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    // The button is disabled on conflicts; re-check in case state changed in between.
    if (findAllConflicts(draftSlots).size > 0) {
      showToast('Ada jam yang bentrok atau terlalu dekat. Perbaiki dulu sebelum menyimpan.', 'error');
      return;
    }
    setSaving(true);
    try {
      const saved = await api.saveSchedule(draftSlots);
      setSavedSlots(saved);
      setDraftSlots(saved);
      if (device?.online) {
        setDevice(await api.getDeviceStatus());
        showToast('Jadwal berhasil disimpan ke Pillbox', 'success');
      } else {
        showToast('Jadwal disimpan, akan dikirim saat Pillbox terhubung kembali', 'warning');
      }
    } catch (err) {
      showToast(failMessage('Gagal menyimpan jadwal', err), 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <View className="flex-1 bg-canvas">
      <StatusBar style="dark" />
      <SafeAreaView style={{ flex: 1 }} edges={needsPairing ? ['top', 'left', 'right', 'bottom'] : ['top', 'left', 'right']}>
        {needsPairing ? (
          <ConnectPillboxScreen onConnected={handleConnected} />
        ) : (
          <>
            <View className="flex-1">
              {tab === 'home' && (
                <HomeTab
                  now={now}
                  pillboxNow={pillboxNowMs}
                  device={device}
                  deviceLoadError={dashboardError}
                  onRetryDevice={handleRetryDashboard}
                  adherence={adherence}
                  savedSlots={savedSlots}
                  recent={recent}
                  refreshing={refreshing}
                  onRefresh={handleRefresh}
                  onOpenTab={openTab}
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
                  testing={testing}
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
                  alarmBusyId={alarmBusyId}
                  actionBusy={doseActionBusy}
                  onAction={handleDoseAction}
                  refreshing={refreshing}
                  onRefresh={handleRefresh}
                  onMarkRead={markRead}
                  onCall={handleCall}
                  onAlarm={handleAlarm}
                  onDelete={handleDelete}
                  onClearAll={handleClearAll}
                />
              )}
              {tab === 'device' && (
                <DeviceTab
                  device={device}
                  connectionBusy={connectionBusy}
                  now={now}
                  loadError={dashboardError}
                  onRetry={handleRetryDashboard}
                  onToggleConnection={handleToggleConnection}
                  refreshing={refreshing}
                  onRefresh={handleRefresh}
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
        )}
      </SafeAreaView>

      <PinPrompt
        visible={releaseTarget !== null}
        title="Buka bilik sekarang?"
        message={`Bilik ${releaseTarget?.slotId ?? ''} akan terbuka sebentar agar obat yang terlewat bisa diminum terlambat. Masukkan PIN pillbox.`}
        confirmLabel="Buka Bilik"
        busy={doseActionBusy?.action === 'LATE_RELEASE'}
        onSubmit={(pin) => void handleRelease(pin)}
        onCancel={() => setReleaseTarget(null)}
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
