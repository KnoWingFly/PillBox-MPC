// Caregiver dashboard for the Smart Pillbox (test harness).
// Data comes from lib/api.ts: the FastAPI backend when EXPO_PUBLIC_PILLBOX_API_URL is set, else mock data.
//
// One screen with four sections (Beranda, Jadwal, Notifikasi, Perangkat) swapped by a bottom tab
// bar. State lives here so the sections share it (e.g. an unsaved schedule survives a tab switch).

import { useRouter } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useState } from 'react';
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
import { ScheduleTab } from '@/components/pillbox/schedule-tab';
import { SettingsTab } from '@/components/pillbox/settings-tab';
import { BackHeader } from '@/components/ui/back-header';
import { TabBar, type TabKey } from '@/components/pillbox/tab-bar';
import { makeToast, Toast, type ToastData } from '@/components/pillbox/toast';
import { LoadErrorBox } from '@/components/pillbox/ui';
import * as tokens from '@/theme/tokens';
import { useAuth } from '@/hooks/use-auth';
import { useDashboardInsights } from '@/hooks/use-dashboard-insights';
import { Strings } from '@/constants/strings';
import { useNotificationFeed } from '@/hooks/use-notification-feed';
import { usePillboxAlarm } from '@/hooks/use-pillbox-alarm';
import { perfLog, perfLoginStep } from '@/lib/perf';
import { DevicesProvider, useDevices } from '@root/context/devices-context';
import * as api from '@root/lib/api';
import { canEdit, type ConnectPillboxResult, type Pillbox } from '@root/lib/devices';
import { NOTIFICATION_DELETE_SUPPORTED } from '@root/lib/notifications';
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

/** The active pillbox no longer exists for this account (unpaired here or by another caregiver). */
function pillboxGone(err: unknown): boolean {
  return err instanceof api.BackendError && (err.code === 'NO_DEVICE' || err.status === 404 || err.status === 403);
}

/** "Gagal …" plus the backend's own message when there is one (e.g. "Device is offline"). */
function failMessage(prefix: string, err: unknown): string {
  return err instanceof api.BackendError ? `${prefix}: ${err.message}` : prefix;
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
  const [carriedTab, setCarriedTab] = useState<TabKey>('home');
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
            text={`Gagal memuat daftar pillbox. Periksa koneksi Anda.${__DEV__ ? `\nServer: ${api.BASE_URL}` : ''}`}
            onRetry={() => void devices.refresh()}
          />
        ) : (
          <ActivityIndicator color={tokens.colors.primary.DEFAULT} />
        )}
      </SafeAreaView>
    );
  }
  return (
    <>
      <PillboxDashboard key={devices.active?.id ?? 'none'} initialTab={carriedTab} onCarry={carry} />
      {carriedToast && <Toast key={carriedToast.id} toast={carriedToast} onDone={hideCarried} />}
    </>
  );
}

function PillboxDashboard({ initialTab, onCarry }: { initialTab: TabKey; onCarry: (carry: Carry) => void }) {
  const devices = useDevices();
  const [tab, setTab] = useState<TabKey>(initialTab);
  const [now, setNow] = useState(() => Date.now());
  const [toast, setToast] = useState<ToastData | null>(null);

  const [device, setDevice] = useState<DeviceStatus | null>(null);
  const [connectionBusy, setConnectionBusy] = useState(false);
  const [dashboardError, setDashboardError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  // Backend mode only: no pillbox is selected because the caregiver has none (or hid them all).
  const needsPairing = !api.USE_MOCK && devices.active === null;
  const [addOpen, setAddOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<Pillbox | null>(null);

  const [savedSlots, setSavedSlots] = useState<Slot[]>([]);
  const [draftSlots, setDraftSlots] = useState<Slot[]>([]);
  const [selectedSlotId, setSelectedSlotId] = useState<SlotId | null>(null);
  const [saving, setSaving] = useState(false);
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
  const [adherence, setAdherence] = useState<AdherenceSummary | null>(null);

  const router = useRouter();
  // Today's doses, weekly chart, elderly profile, clock and preferences; days follow the pillbox clock.
  const insights = useDashboardInsights(pillboxNow(device, now), !needsPairing);
  const refreshDoses = insights.refreshDoses;
  const [remindBusy, setRemindBusy] = useState(false);
  const [calibrateOpen, setCalibrateOpen] = useState(false);
  const [calibrateBusy, setCalibrateBusy] = useState(false);

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

  // New notifications trigger the banner; dose events also change adherence.
  const handleArrive = useCallback(
    (n: AppNotification) => {
      perfLog('iot_to_app', 'shown_on_screen', { notification_id: n.id });
      setToast(makeToast(n.slotId ? `${n.title} · ${n.slotId}` : n.title, notificationLook(n).toast));
      setNow(Date.now());
      if (n.type !== 'system') {
        refreshAdherence();
        refreshDoses();
      }
    },
    [refreshAdherence, refreshDoses],
  );
  const feed = useNotificationFeed({ onArrive: handleArrive });

  const showToast = (text: string, tone: ToastTone) => setToast(makeToast(text, tone));
  const hideToast = useCallback((id: number) => {
    setToast((current) => (current?.id === id ? null : current));
  }, []);

  // Initial load from the data layer. Pairing or switching pillboxes remounts the dashboard instead.
  useEffect(() => {
    if (needsPairing) return;
    let cancelled = false;
    Promise.all([api.getDeviceStatus(), api.getSchedules()])
      .then(([status, slots]) => {
        if (cancelled) return;
        setDashboardError(false);
        setDevice(status);
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
        setToast(makeToast(failMessage('Gagal memuat data perangkat', err), 'error'));
      });
    api
      .getAdherenceSummary()
      .then((summary) => {
        if (!cancelled) setAdherence(summary);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // `devices` is read only on failure; re-running on its changes would refetch on every list poll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsPairing]);

  // Backend mode: online/offline, battery and last sync change on the device side. The backend
  // pushes a hint when they change; the interval is the fallback when the socket is down.
  useEffect(() => {
    if (api.USE_MOCK || needsPairing) return;
    let lastFetchAt = 0;
    const refresh = (force = false) => {
      // Pushed changes already arrive over the socket; then poll only as a slow safety net.
      if (!force && api.isRealtimeLive() && Date.now() - lastFetchAt < api.REALTIME_FALLBACK_POLL_MS) return;
      lastFetchAt = Date.now();
      api.getDeviceStatus().then(setDevice).catch(() => undefined);
    };
    const timer = setInterval(() => refresh(), AppConfig.deviceStatusPollMs);
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
      else refresh(true);
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
  const deviceTone = device ? deviceLook(device, now).tone : dashboardError ? 'missed' : null;
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
    try {
      const [status, slots] = await Promise.all([api.getDeviceStatus(), api.getSchedules()]);
      setDevice(status);
      setSavedSlots(slots);
      if (!keepDraft) setDraftSlots(slots);
      setDashboardError(false);
    } catch (err) {
      if (pillboxGone(err)) void devices.refresh();
      else setDashboardError(true);
    }
  };

  const handleConnected = async (result: ConnectPillboxResult) => {
    const linked = result.joined ? 'Bergabung ke pillbox (mode pemantau)' : 'Pillbox berhasil dihubungkan';
    const message =
      result.online === false
        ? makeToast(`${linked}, tetapi pillbox sedang offline. Pastikan pillbox menyala dan terhubung internet.`, 'warning')
        : makeToast(linked, 'success');
    setAddOpen(false);
    api.resubscribeRealtime();
    // The new pillbox becomes active, which remounts this dashboard: hand the toast over.
    onCarry({ tab: 'home', toast: message });
    try {
      await devices.added(result.deviceId);
    } catch {
      setToast(makeToast('Pillbox terhubung. Tarik ke bawah untuk memuat ulang daftar.', 'warning'));
    }
  };

  /** Switches the active pillbox; an unsaved schedule draft would be lost, so ask first. */
  const handleSelectPillbox = (pillbox: Pillbox) => {
    const go = () => {
      onCarry({ tab, toast: makeToast(`Menampilkan ${pillbox.name}`, 'info') });
      devices.select(pillbox.id);
    };
    if (!draftDirty) return go();
    setConfirmRequest({
      title: 'Pindah pillbox?',
      message: 'Perubahan jadwal yang belum disimpan akan hilang.',
      confirmLabel: 'Pindah',
      cancelLabel: 'Tetap di sini',
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
      showToast('Nama pillbox diperbarui', 'success');
      if (target.id === devices.active?.id) setDevice((prev) => (prev ? { ...prev, deviceName: name } : prev));
    } else showToast('Gagal mengubah nama. Nama sebelumnya dikembalikan.', 'error');
  };

  const handleRemovePillbox = (pillbox: Pillbox) => {
    const elderly = pillbox.elderlyName ? ` "${pillbox.elderlyName}"` : '';
    setConfirmRequest({
      title: `Hapus "${pillbox.name}"?`,
      message:
        `Tindakan ini permanen dan tidak bisa dibatalkan:\n` +
        `• Pillbox ${pillbox.code} dilepas dari profil lansia${elderly} untuk SEMUA pengasuh yang terhubung, bukan hanya Anda.\n` +
        `• Semua jadwal pillbox ini di Kontrol Jadwal dihapus.\n` +
        `• Riwayat notifikasi pillbox ini di akun Anda dihapus.\n` +
        `Riwayat minum obat lansia tetap tersimpan. Untuk memakai pillbox ini lagi, pasangkan ulang dengan PIN baru.`,
      confirmLabel: 'Hapus Permanen',
      tone: 'danger',
      icon: 'trash-outline',
      onConfirm: async () => {
        const wasActive = pillbox.id === devices.active?.id;
        // Removing the active pillbox remounts the dashboard: the result toast is handed over.
        if (wasActive) onCarry({ tab: 'device' });
        const result = await devices.remove(pillbox);
        const message = !result
          ? makeToast(`Gagal menghapus "${pillbox.name}". Pillbox dikembalikan ke daftar.`, 'error')
          : result.notificationsFailed !== 0
            ? makeToast(`"${pillbox.name}" dihapus, tetapi sebagian riwayat notifikasinya gagal dihapus.`, 'warning')
            : makeToast(`"${pillbox.name}" dihapus`, 'success');
        if (wasActive && result) onCarry({ tab: 'device', toast: message });
        else setToast(message);
      },
    });
  };

  const handleHidePillbox = (pillbox: Pillbox) => {
    setConfirmRequest({
      title: `Sembunyikan "${pillbox.name}"?`,
      message:
        'Pillbox hanya disembunyikan di HP ini. Anda tetap terhubung sebagai ' +
        (pillbox.myRole === 'ADMIN' ? 'admin' : 'pemantau') +
        ' di server, dan hanya pemilik yang dapat melepas pillbox. Anda bisa menampilkannya lagi dari tab Perangkat.',
      confirmLabel: 'Sembunyikan',
      tone: 'warning',
      icon: 'eye-off-outline',
      onConfirm: async () => {
        if (pillbox.id === devices.active?.id) onCarry({ tab: 'device', toast: makeToast(`"${pillbox.name}" disembunyikan`, 'info') });
        if (!(await devices.hide(pillbox.id))) showToast('Gagal menyembunyikan pillbox', 'error');
      },
    });
  };

  const findExisting = (code: string) => {
    const found = devices.all.find((p) => p.code === code);
    return found ? { id: found.id, name: found.name, hidden: devices.hidden.some((h) => h.id === found.id) } : null;
  };

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
      insights.refreshDoses();
      showToast('45 riwayat contoh ditambahkan', 'success');
    } catch {
      showToast('Gagal menambah riwayat contoh', 'error');
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
    if (!(await feed.remove(n.id))) showToast('Gagal menghapus. Notifikasi dikembalikan.', 'error');
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

  const handleSignOut = () => {
    setConfirmRequest({
      title: 'Keluar dari akun?',
      message: 'Anda perlu masuk kembali untuk melihat pillbox. Notifikasi push ke HP ini akan berhenti.',
      confirmLabel: 'Keluar',
      tone: 'danger',
      icon: 'log-out-outline',
      onConfirm: signOut,
    });
  };

  const handleClearAll = () => {
    setConfirmRequest({
      title: 'Hapus semua notifikasi?',
      message:
        `Semua notifikasi ${devices.active?.name ?? 'pillbox ini'}, termasuk yang tidak tampil di filter ini, akan dihapus ` +
        'permanen dan tidak bisa dikembalikan. Notifikasi pillbox lain dan milik pengasuh lain tidak ikut terhapus.',
      confirmLabel: 'Hapus Semua',
      tone: 'danger',
      icon: 'trash-outline',
      onConfirm: async () => {
        if (await feed.clearAll()) {
              showToast('Semua notifikasi dihapus', 'success');
        } else {
          showToast('Gagal menghapus. Notifikasi dikembalikan.', 'error');
        }
      },
    });
  };

  /** Calls the elderly's own number when the profile has one, else the configured placeholder. */
  const callElder = async () => {
    try {
      await Linking.openURL(`tel:${insights.elderly?.contactPhone ?? AppConfig.elderPhone}`);
    } catch {
      showToast('Tidak dapat membuka aplikasi telepon', 'error');
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
      showToast(`Alarm dibunyikan di ${device?.deviceName ?? 'Pillbox'}`, 'success');
    } catch (err) {
      // e.g. "Device is offline; the command was not sent" from the backend
      showToast(failMessage('Gagal membunyikan alarm', err), 'error');
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
      // No status re-read: a schedule save does not change it, and /ws/app pushes status changes.
      if (device?.online) {
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
          <ConnectPillboxScreen
            onConnected={(r) => void handleConnected(r)}
            findExisting={findExisting}
            onUnhide={() => void devices.unhideAll()}
            hiddenCount={devices.hidden.length}
            onSignOut={handleSignOut}
          />
        ) : (
          <>
            <TopBar userName={user?.full_name ?? Strings.shell.caregiverFallback} />
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
                  onCall={() => void callElder()}
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
                  onCall={handleCall}
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
                  prefsBusy={insights.prefsBusy}
                  onTogglePreference={(key, value) => void handleTogglePreference(key, value)}
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
        )}
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
        title="Buka bilik sekarang?"
        message={`Bilik ${releaseTarget?.slotId ?? ''} akan terbuka sebentar agar obat yang terlewat bisa diminum terlambat. Masukkan PIN pillbox.`}
        confirmLabel="Buka Bilik"
        busy={doseActionBusy?.action === 'LATE_RELEASE'}
        onSubmit={(pin) => void handleRelease(pin)}
        onCancel={() => setReleaseTarget(null)}
      />
      <Modal visible={addOpen} animationType="slide" onRequestClose={() => setAddOpen(false)} presentationStyle="pageSheet">
        <SafeAreaView style={{ flex: 1 }} className="bg-canvas">
          <ConnectPillboxScreen
            onConnected={(r) => void handleConnected(r)}
            findExisting={findExisting}
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
