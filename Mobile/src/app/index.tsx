// Caregiver dashboard for the Smart Pillbox (test harness).
// Everything runs against the mock data layer in lib/api.ts (USE_MOCK = true).
//
// One screen with four sections (Beranda, Jadwal, Notifikasi, Perangkat) swapped by a bottom tab
// bar. State lives here so the sections share it (e.g. an unsaved schedule survives a tab switch).

import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useState } from 'react';
import { Alert, BackHandler, Linking, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DeviceTab } from '@/components/pillbox/device-tab';
import { deviceLook, isDraftDirty, isSlotActive, notificationLook, type ToastTone } from '@/components/pillbox/helpers';
import { HomeTab } from '@/components/pillbox/home-tab';
import { NotificationsTab } from '@/components/pillbox/notifications-tab';
import { ScheduleTab } from '@/components/pillbox/schedule-tab';
import { TabBar, type TabKey } from '@/components/pillbox/tab-bar';
import { makeToast, Toast, type ToastData } from '@/components/pillbox/toast';
import { useNotificationFeed } from '@/hooks/use-notification-feed';
import * as api from '@root/lib/api';
import { fetchNotificationPage } from '@root/lib/notifications';
import { findAllDuplicates } from '@root/lib/schedule-time';
import type { AdherenceSummary, AppNotification, DeviceStatus, DoseEventType, Slot, SlotId } from '@root/lib/types';

// Placeholder only; replace with the elder's real number once profiles exist.
const ELDER_PHONE = '+620000000000';
const RECENT_COUNT = 3;

export default function PillboxDashboard() {
  const [tab, setTab] = useState<TabKey>('home');
  const [now, setNow] = useState(() => Date.now());
  const [toast, setToast] = useState<ToastData | null>(null);

  const [device, setDevice] = useState<DeviceStatus | null>(null);
  const [connectionBusy, setConnectionBusy] = useState(false);
  const [dashboardError, setDashboardError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const [savedSlots, setSavedSlots] = useState<Slot[]>([]);
  const [draftSlots, setDraftSlots] = useState<Slot[]>([]);
  const [selectedSlotId, setSelectedSlotId] = useState<SlotId | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const [alarmBusyId, setAlarmBusyId] = useState<string | null>(null);
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

  // Initial load from the data layer.
  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getDeviceStatus(), api.getSchedules()])
      .then(([status, slots]) => {
        if (cancelled) return;
        setDevice(status);
        setSavedSlots(slots);
        setDraftSlots(slots);
      })
      .catch(() => {
        if (!cancelled) setDashboardError(true);
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
  }, []);

  // Keeps relative times ("5 menit lalu") fresh.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);

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
    } catch {
      setDashboardError(true);
    }
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

  const handleClearAll = () => {
    Alert.alert(
      'Hapus semua notifikasi?',
      'Semua notifikasi, termasuk yang tidak tampil di filter ini, akan dihapus permanen dan tidak bisa dikembalikan.',
      [
        { text: 'Batal', style: 'cancel' },
        {
          text: 'Hapus',
          style: 'destructive',
          onPress: async () => {
            if (await feed.clearAll()) {
              refreshRecent();
              showToast('Semua notifikasi dihapus', 'success');
            } else {
              showToast('Gagal menghapus. Notifikasi dikembalikan.', 'error');
            }
          },
        },
      ],
      { cancelable: true },
    );
  };

  const handleCall = async (n: AppNotification) => {
    markRead(n.id);
    try {
      await Linking.openURL(`tel:${ELDER_PHONE}`);
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
    } catch {
      showToast('Gagal membunyikan alarm', 'error');
    } finally {
      setAlarmBusyId(null);
    }
  };

  const handleChangeSlot = (id: SlotId, patch: Partial<Slot>) => {
    setDraftSlots((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  };

  const handleDiscard = () => {
    Alert.alert('Batalkan perubahan?', 'Jadwal kembali seperti yang tersimpan di Pillbox.', [
      { text: 'Tidak', style: 'cancel' },
      { text: 'Batalkan perubahan', style: 'destructive', onPress: () => setDraftSlots(savedSlots) },
    ]);
  };

  const handleTestSlot = async (id: SlotId) => {
    setTesting(true);
    try {
      await api.triggerTestSlot(id);
      showToast(`Tes pengingat dikirim ke slot ${id}`, 'success');
    } catch {
      showToast('Gagal mengirim tes pengingat', 'error');
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    // The button is disabled on conflicts; re-check in case state changed in between.
    if (findAllDuplicates(draftSlots).size > 0) {
      showToast('Ada jam yang bentrok. Perbaiki dulu sebelum menyimpan.', 'error');
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
    } catch {
      showToast('Gagal menyimpan jadwal', 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <View className="flex-1 bg-canvas">
      <StatusBar style="dark" />
      <SafeAreaView style={{ flex: 1 }} edges={['top', 'left', 'right']}>
        <View className="flex-1">
          {tab === 'home' && (
            <HomeTab
              now={now}
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
              now={now}
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
              now={now}
              alarmBusyId={alarmBusyId}
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
      </SafeAreaView>

      {toast && <Toast key={toast.id} toast={toast} onDone={hideToast} />}
    </View>
  );
}
