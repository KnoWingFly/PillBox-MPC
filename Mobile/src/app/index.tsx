// Frontend-only test harness for the Smart Pillbox caregiver app.
// Data comes from lib/api.ts: the FastAPI backend when EXPO_PUBLIC_PILLBOX_API_URL is set, else mock data.

import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useState, type ComponentProps, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Animated,
  Linking,
  Pressable,
  ScrollView,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import * as api from '@root/lib/api';
import {
  SLOT_IDS,
  type AdherenceSummary,
  type AppNotification,
  type DeviceStatus,
  type DoseEventType,
  type NotificationType,
  type Slot,
  type SlotId,
  type ToleranceMinutes,
} from '@root/lib/types';

// ---------------------------------------------------------------------------
// Constants & helpers
// ---------------------------------------------------------------------------

const PRIMARY = '#00539B';
// Placeholder only; replace with the elder's real number once profiles exist.
const ELDER_PHONE = '+620000000000';
const TOAST_DURATION_MS = 3000;
const TIME_STEP_MINUTES = 5;
const MINUTES_PER_DAY = 24 * 60;
/** Used when an empty slot gets its first time: Pagi, Siang, Sore, Malam. */
const COLUMN_DEFAULT_TIMES = [7 * 60, 12 * 60, 18 * 60, 21 * 60] as const;
const COLUMNS = ['Pagi', 'Siang', 'Sore', 'Malam'] as const;
const ROWS = [
  { key: 'A', label: 'Sebelum Makan' },
  { key: 'B', label: 'Sesudah Makan' },
] as const;
const TOLERANCE_OPTIONS: { value: ToleranceMinutes; label: string }[] = [
  { value: 15, label: '15 mnt' },
  { value: 30, label: '30 mnt' },
  { value: 45, label: '45 mnt' },
  { value: 60, label: '1 jam' },
];

type ToastTone = 'success' | 'info' | 'warning' | 'error';
type ToastData = { id: number; text: string; tone: ToastTone };
type FilterKey = 'all' | 'issues' | 'system';

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'Semua' },
  { key: 'issues', label: 'Terlambat & Terlewat' },
  { key: 'system', label: 'Sistem' },
];

const TOAST_BG: Record<ToastTone, string> = {
  success: 'bg-green-600',
  info: 'bg-primary',
  warning: 'bg-orange-500',
  error: 'bg-red-600',
};

const NOTIFICATION_STYLE: Record<
  NotificationType,
  { label: string; badge: string; badgeText: string; accent: string; tone: ToastTone }
> = {
  on_time: { label: 'Tepat Waktu', badge: 'bg-green-100', badgeText: 'text-green-800', accent: 'border-l-green-600', tone: 'success' },
  late: { label: 'Terlambat', badge: 'bg-orange-100', badgeText: 'text-orange-800', accent: 'border-l-orange-500', tone: 'warning' },
  missed: { label: 'Terlewat', badge: 'bg-red-100', badgeText: 'text-red-800', accent: 'border-l-red-600', tone: 'error' },
  system: { label: 'Sistem', badge: 'bg-blue-100', badgeText: 'text-blue-800', accent: 'border-l-primary', tone: 'info' },
};

let toastSeq = 0;
function makeToast(text: string, tone: ToastTone): ToastData {
  toastSeq += 1;
  return { id: toastSeq, text, tone };
}

function isSlotActive(slot: Slot | undefined): boolean {
  return !!slot && slot.enabled && slot.timeMinutes !== null;
}

function slotsEqual(a: Slot, b: Slot): boolean {
  return (
    a.timeMinutes === b.timeMinutes &&
    a.enabled === b.enabled &&
    a.toleranceMinutes === b.toleranceMinutes &&
    a.stock === b.stock
  );
}

function columnIndex(id: SlotId): number {
  return Number(id[1]) - 1;
}

function formatRelative(timestamp: number, now: number): string {
  const minutes = Math.floor(Math.max(0, now - timestamp) / 60000);
  if (minutes < 1) return 'Baru saja';
  if (minutes < 60) return `${minutes} mnt lalu`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} jam lalu`;
  return `${Math.floor(hours / 24)} hari lalu`;
}

function computeAdherence(notifications: AppNotification[]): AdherenceSummary {
  let onTime = 0;
  let late = 0;
  let missed = 0;
  let delaySum = 0;
  for (const n of notifications) {
    if (n.type === 'on_time') onTime += 1;
    else if (n.type === 'late') {
      late += 1;
      delaySum += n.minutesLate ?? 0;
    } else if (n.type === 'missed') missed += 1;
  }
  const total = onTime + late + missed;
  const taken = onTime + late;
  return {
    totalDoses: total,
    onTimeDoses: onTime,
    lateDoses: late,
    missedDoses: missed,
    adherencePercent: total > 0 ? Math.round((onTime / total) * 100) : null,
    averageDelayMinutes: taken > 0 ? Math.round(delaySum / taken) : null,
  };
}

function matchesFilter(n: AppNotification, filter: FilterKey): boolean {
  if (filter === 'issues') return n.type === 'late' || n.type === 'missed';
  if (filter === 'system') return n.type === 'system';
  return true;
}

// ---------------------------------------------------------------------------
// Small building blocks
// ---------------------------------------------------------------------------

type ButtonVariant = 'primary' | 'outline' | 'success' | 'warning' | 'danger';

const BUTTON_STYLE: Record<ButtonVariant, { container: string; text: string; spinner: string }> = {
  primary: { container: 'bg-primary', text: 'text-white', spinner: '#FFFFFF' },
  outline: { container: 'bg-white border-2 border-primary', text: 'text-primary', spinner: PRIMARY },
  success: { container: 'bg-green-600', text: 'text-white', spinner: '#FFFFFF' },
  warning: { container: 'bg-orange-500', text: 'text-white', spinner: '#FFFFFF' },
  danger: { container: 'bg-red-600', text: 'text-white', spinner: '#FFFFFF' },
};

function Button({
  label,
  onPress,
  variant = 'primary',
  disabled = false,
  loading = false,
  compact = false,
}: {
  label: string;
  onPress: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  loading?: boolean;
  compact?: boolean;
}) {
  const style = BUTTON_STYLE[variant];
  const inactive = disabled || loading;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: inactive, busy: loading }}
      disabled={inactive}
      onPress={onPress}
      className={`min-h-[48px] flex-row items-center justify-center rounded-xl active:opacity-70 ${
        compact ? 'px-3' : 'px-4'
      } ${style.container} ${inactive ? 'opacity-50' : ''}`}>
      {loading ? (
        <ActivityIndicator color={style.spinner} />
      ) : (
        <Text className={`text-center text-lg font-semibold ${style.text}`}>{label}</Text>
      )}
    </Pressable>
  );
}

function Chip({
  label,
  selected,
  onPress,
  disabled = false,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
  disabled?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ selected, disabled }}
      disabled={disabled}
      onPress={onPress}
      className={`min-h-[44px] min-w-[44px] items-center justify-center rounded-full border-2 px-4 active:opacity-70 ${
        selected ? 'border-primary bg-primary' : 'border-slate-300 bg-white'
      } ${disabled ? 'opacity-40' : ''}`}>
      <Text className={`text-lg font-semibold ${selected ? 'text-white' : 'text-slate-700'}`}>{label}</Text>
    </Pressable>
  );
}

function Card({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <View className="gap-4 rounded-3xl bg-white p-5 shadow-sm">
      <View className="flex-row items-center justify-between gap-2">
        <Text className="shrink text-2xl font-bold text-slate-900" accessibilityRole="header">
          {title}
        </Text>
        {right}
      </View>
      {children}
    </View>
  );
}

function Toast({ toast, onDone }: { toast: ToastData; onDone: (id: number) => void }) {
  const insets = useSafeAreaInsets();
  const [progress] = useState(() => new Animated.Value(0));

  useEffect(() => {
    const animation = Animated.sequence([
      Animated.timing(progress, { toValue: 1, duration: 220, useNativeDriver: true }),
      Animated.delay(TOAST_DURATION_MS - 440),
      Animated.timing(progress, { toValue: 0, duration: 220, useNativeDriver: true }),
    ]);
    animation.start(({ finished }) => {
      if (finished) onDone(toast.id);
    });
    return () => animation.stop();
  }, [progress, onDone, toast.id]);

  const translateY = progress.interpolate({ inputRange: [0, 1], outputRange: [-120, 0] });

  return (
    <Animated.View
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
      style={{
        position: 'absolute',
        top: insets.top + 8,
        left: 16,
        right: 16,
        zIndex: 50,
        elevation: 8,
        opacity: progress,
        transform: [{ translateY }],
        pointerEvents: 'none',
      }}>
      <View className={`rounded-2xl px-5 py-4 shadow-lg ${TOAST_BG[toast.tone]}`}>
        <Text className="text-lg font-semibold text-white">{toast.text}</Text>
      </View>
    </Animated.View>
  );
}

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

function AdherenceCard({ summary }: { summary: AdherenceSummary }) {
  return (
    <View className="gap-3 rounded-3xl bg-primary p-5">
      <View className="flex-row gap-3">
        <View className="flex-1 rounded-2xl bg-white/15 p-4">
          <Text className="text-base text-white/80">Kepatuhan</Text>
          <Text className="text-4xl font-bold text-white">
            {summary.adherencePercent === null ? '-' : `${summary.adherencePercent}%`}
          </Text>
        </View>
        <View className="flex-1 rounded-2xl bg-white/15 p-4">
          <Text className="text-base text-white/80">Rata-rata terlambat</Text>
          <Text className="text-4xl font-bold text-white">
            {summary.averageDelayMinutes === null ? '-' : `${summary.averageDelayMinutes} mnt`}
          </Text>
        </View>
      </View>
      <Text className="text-base text-white/90">
        {summary.totalDoses} dosis tercatat · Tepat {summary.onTimeDoses} · Terlambat {summary.lateDoses} · Terlewat{' '}
        {summary.missedDoses}
      </Text>
    </View>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <View className="flex-row items-center justify-between">
      <Text className="text-lg text-slate-500">{label}</Text>
      <Text className="text-lg font-semibold text-slate-900">{value}</Text>
    </View>
  );
}

function ConnectionCard({
  device,
  busy,
  now,
  onToggle,
}: {
  device: DeviceStatus | null;
  busy: boolean;
  now: number;
  onToggle: () => void;
}) {
  if (!device) {
    return (
      <Card title="Status Perangkat">
        <ActivityIndicator color={PRIMARY} />
      </Card>
    );
  }
  return (
    <Card
      title="Status Perangkat"
      right={
        <View
          className={`flex-row items-center gap-2 rounded-full px-3 py-1 ${
            device.online ? 'bg-green-100' : 'bg-red-100'
          }`}>
          <View className={`h-3 w-3 rounded-full ${device.online ? 'bg-green-600' : 'bg-red-600'}`} />
          <Text className={`text-base font-bold ${device.online ? 'text-green-800' : 'text-red-800'}`}>
            {device.online ? 'Online & Aktif' : 'Offline'}
          </Text>
        </View>
      }>
      <Text className="text-xl font-semibold text-slate-900">{device.deviceName}</Text>
      <View className="gap-2">
        <InfoRow label="Baterai" value={`${device.batteryPercent}%`} />
        <InfoRow label="Wi-Fi" value={device.online ? device.wifiLabel : 'Tidak terhubung'} />
        <InfoRow label="Sinkron terakhir" value={formatRelative(device.lastSyncedAt, now)} />
      </View>
      {/* With the real backend, connectivity comes from the device itself (emulator Wi-Fi toggle). */}
      {api.USE_MOCK && (
        <Button
          label={device.online ? 'Simulasi Putuskan Koneksi' : 'Simulasi Sambungkan'}
          variant="outline"
          loading={busy}
          onPress={onToggle}
        />
      )}
    </Card>
  );
}

const CONNECT_ERRORS: Record<string, string> = {
  QR_CODE_NOT_RECOGNIZED: 'Kode perangkat tidak dikenal. Daftarkan dulu dari emulator (tombol "Daftarkan Perangkat").',
  DEVICE_PIN_INVALID: 'PIN harus 4 digit angka.',
  DEVICE_PIN_INCORRECT: 'PIN salah untuk pillbox yang sudah terpasang.',
  TOO_MANY_ATTEMPTS: 'Terlalu banyak percobaan PIN. Coba lagi beberapa menit lagi.',
  NETWORK_ERROR: 'Server tidak dapat dihubungi. Pastikan backend berjalan.',
};

function ConnectInput({
  label,
  ...props
}: { label: string } & ComponentProps<typeof TextInput>) {
  return (
    <View className="gap-1">
      <Text className="text-base font-semibold text-slate-700">{label}</Text>
      <TextInput
        className="min-h-[48px] rounded-xl border-2 border-slate-300 bg-white px-4 text-lg text-slate-900"
        placeholderTextColor="#94A3B8"
        autoCorrect={false}
        {...props}
      />
    </View>
  );
}

function ConnectPillboxCard({ onConnected }: { onConnected: (result: api.ConnectPillboxResult) => void }) {
  const [deviceCode, setDeviceCode] = useState('');
  const [pin, setPin] = useState('');
  const [nickname, setNickname] = useState('Pillbox Lansia');
  const [elderlyName, setElderlyName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = deviceCode.trim().length > 0 && /^\d{4}$/.test(pin);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      onConnected(await api.connectPillbox({ deviceCode, pin, nickname, elderlyName }));
    } catch (err) {
      if (err instanceof api.BackendError) setError(CONNECT_ERRORS[err.code] ?? err.message);
      else setError('Gagal menghubungkan pillbox.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Hubungkan Pillbox">
      <Text className="text-base text-slate-600">
        Di emulator Smart Device, tekan "Daftarkan Perangkat" pada panel "Koneksi Server", lalu ketik kode yang
        muncul di sini. Buat PIN 4 digit baru; jika pillbox sudah dipasangkan caregiver lain, masukkan PIN-nya
        untuk bergabung.
      </Text>
      <ConnectInput
        label="Kode perangkat"
        value={deviceCode}
        onChangeText={setDeviceCode}
        placeholder="PB-1A2B3C4D"
        autoCapitalize="characters"
      />
      <ConnectInput
        label="PIN perangkat (4 digit)"
        value={pin}
        onChangeText={(v) => setPin(v.replace(/\D/g, '').slice(0, 4))}
        placeholder="1234"
        keyboardType="number-pad"
        secureTextEntry
        maxLength={4}
      />
      <ConnectInput label="Nama pillbox" value={nickname} onChangeText={setNickname} />
      <ConnectInput
        label="Nama lansia (jika belum ada profil)"
        value={elderlyName}
        onChangeText={setElderlyName}
        placeholder="mis. Oma Sari"
      />
      {error && <Text className="text-base font-semibold text-red-700">{error}</Text>}
      <Button label="Hubungkan" onPress={submit} loading={busy} disabled={!canSubmit} />
    </Card>
  );
}

function SimulatorCard({
  slots,
  slotId,
  onSelectSlot,
  minutesLate,
  onChangeMinutesLate,
  busyType,
  onSimulate,
}: {
  slots: Slot[];
  slotId: SlotId | null;
  onSelectSlot: (id: SlotId) => void;
  minutesLate: number;
  onChangeMinutesLate: (value: number) => void;
  busyType: DoseEventType | null;
  onSimulate: (type: DoseEventType) => void;
}) {
  const disabled = slotId === null || busyType !== null;
  return (
    <Card title="Simulasi Event IoT">
      <Text className="text-lg text-slate-600">
        Pilih slot (hanya slot aktif yang tersimpan di Pillbox), lalu kirim event.
      </Text>
      <View className="flex-row flex-wrap gap-2">
        {SLOT_IDS.map((id) => (
          <Chip
            key={id}
            label={id}
            selected={slotId === id}
            disabled={!isSlotActive(slots.find((s) => s.id === id))}
            onPress={() => onSelectSlot(id)}
          />
        ))}
      </View>
      {slotId === null && <Text className="text-lg text-red-700">Tidak ada slot aktif.</Text>}

      <View className="flex-row items-center justify-between">
        <Text className="text-lg text-slate-700">Menit terlambat</Text>
        <View className="flex-row items-center gap-3">
          <Button
            label="−5"
            variant="outline"
            compact
            disabled={minutesLate <= 5}
            onPress={() => onChangeMinutesLate(minutesLate - 5)}
          />
          <Text className="w-12 text-center text-xl font-bold text-slate-900">{minutesLate}</Text>
          <Button
            label="+5"
            variant="outline"
            compact
            disabled={minutesLate >= 180}
            onPress={() => onChangeMinutesLate(minutesLate + 5)}
          />
        </View>
      </View>

      <View className="gap-3">
        <Button
          label="Obat Diminum Tepat Waktu"
          variant="success"
          disabled={disabled}
          loading={busyType === 'on_time'}
          onPress={() => onSimulate('on_time')}
        />
        <Button
          label={`Obat Diminum Terlambat (${minutesLate} mnt)`}
          variant="warning"
          disabled={disabled}
          loading={busyType === 'late'}
          onPress={() => onSimulate('late')}
        />
        <Button
          label="Dosis Terlewat"
          variant="danger"
          disabled={disabled}
          loading={busyType === 'missed'}
          onPress={() => onSimulate('missed')}
        />
      </View>
    </Card>
  );
}

function NotificationItem({
  notification,
  now,
  alarmBusy,
  onPress,
  onCall,
  onAlarm,
}: {
  notification: AppNotification;
  now: number;
  alarmBusy: boolean;
  onPress: () => void;
  onCall: () => void;
  onAlarm: () => void;
}) {
  const style = NOTIFICATION_STYLE[notification.type];
  const needsAction = notification.type === 'late' || notification.type === 'missed';
  const slotLabel = notification.slotId
    ? `Slot ${notification.slotId} · ${api.getSlotColumnLabel(notification.slotId)}`
    : null;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${notification.read ? '' : 'Belum dibaca. '}${notification.title}. ${notification.message}`}
      accessibilityHint="Ketuk untuk menandai sudah dibaca"
      onPress={onPress}
      className={`gap-3 rounded-2xl border border-l-8 border-slate-200 p-4 active:opacity-80 ${style.accent} ${
        notification.read ? 'bg-slate-50' : 'bg-white'
      }`}>
      <View className="flex-row flex-wrap items-center gap-2">
        <View className={`rounded-full px-3 py-1 ${style.badge}`}>
          <Text className={`text-base font-bold ${style.badgeText}`}>{style.label}</Text>
        </View>
        {slotLabel && <Text className="text-base font-semibold text-slate-600">{slotLabel}</Text>}
        <View className="flex-1" />
        {!notification.read && <View className="h-3 w-3 rounded-full bg-red-600" />}
        <Text className="text-base text-slate-500">{formatRelative(notification.createdAt, now)}</Text>
      </View>
      <Text className={`text-xl text-slate-900 ${notification.read ? 'font-semibold' : 'font-bold'}`}>
        {notification.title}
      </Text>
      <Text className="text-lg text-slate-700">{notification.message}</Text>
      {needsAction && (
        <View className="flex-row gap-3">
          <View className="flex-1">
            <Button label="Hubungi Lansia" variant="outline" compact onPress={onCall} />
          </View>
          <View className="flex-1">
            <Button label="Trigger Alarm" variant="danger" compact loading={alarmBusy} onPress={onAlarm} />
          </View>
        </View>
      )}
    </Pressable>
  );
}

function NotificationCenter({
  notifications,
  filter,
  onFilter,
  now,
  alarmBusyId,
  onMarkRead,
  onCall,
  onAlarm,
}: {
  notifications: AppNotification[];
  filter: FilterKey;
  onFilter: (filter: FilterKey) => void;
  now: number;
  alarmBusyId: string | null;
  onMarkRead: (id: string) => void;
  onCall: (n: AppNotification) => void;
  onAlarm: (n: AppNotification) => void;
}) {
  const unread = notifications.filter((n) => !n.read).length;
  const visible = notifications.filter((n) => matchesFilter(n, filter));

  return (
    <Card
      title="Notifikasi"
      right={
        unread > 0 ? (
          <View
            accessibilityLabel={`${unread} notifikasi belum dibaca`}
            className="min-w-[32px] items-center rounded-full bg-red-600 px-3 py-1">
            <Text className="text-lg font-bold text-white">{unread}</Text>
          </View>
        ) : null
      }>
      <View className="flex-row flex-wrap gap-2">
        {FILTERS.map((f) => (
          <Chip key={f.key} label={f.label} selected={filter === f.key} onPress={() => onFilter(f.key)} />
        ))}
      </View>
      {visible.length === 0 ? (
        <Text className="py-4 text-center text-lg text-slate-500">
          Belum ada notifikasi. Gunakan Simulasi Event IoT di atas.
        </Text>
      ) : (
        <View className="gap-3">
          {visible.map((n) => (
            <NotificationItem
              key={n.id}
              notification={n}
              now={now}
              alarmBusy={alarmBusyId === n.id}
              onPress={() => onMarkRead(n.id)}
              onCall={() => onCall(n)}
              onAlarm={() => onAlarm(n)}
            />
          ))}
        </View>
      )}
    </Card>
  );
}

function SlotCell({
  slot,
  selected,
  changed,
  onPress,
}: {
  slot: Slot;
  selected: boolean;
  changed: boolean;
  onPress: () => void;
}) {
  const active = isSlotActive(slot);
  const empty = slot.timeMinutes === null;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Slot ${slot.id}, ${empty ? 'kosong' : api.formatTime(slot.timeMinutes)}, ${
        active ? 'aktif' : 'nonaktif'
      }`}
      accessibilityState={{ selected }}
      onPress={onPress}
      className={`min-h-[88px] flex-1 items-center justify-center gap-1 rounded-2xl border-2 p-2 active:opacity-70 ${
        selected ? 'border-primary bg-primary-light' : 'border-slate-200 bg-white'
      }`}>
      <View className="flex-row items-center gap-1">
        <View className={`h-2.5 w-2.5 rounded-full ${active ? 'bg-green-600' : 'bg-slate-300'}`} />
        <Text className="text-lg font-bold text-slate-900">
          {slot.id}
          {changed ? '*' : ''}
        </Text>
      </View>
      <Text className={`text-lg ${empty ? 'italic text-slate-400' : 'font-semibold text-slate-800'}`}>
        {empty ? 'Kosong' : api.formatTime(slot.timeMinutes)}
      </Text>
    </Pressable>
  );
}

function SlotEditor({
  slot,
  testing,
  onChange,
  onTest,
}: {
  slot: Slot;
  testing: boolean;
  onChange: (patch: Partial<Slot>) => void;
  onTest: () => void;
}) {
  const defaultTime = COLUMN_DEFAULT_TIMES[columnIndex(slot.id)];

  const shiftTime = (delta: number) => {
    if (slot.timeMinutes === null) {
      onChange({ timeMinutes: defaultTime });
      return;
    }
    const next = (((slot.timeMinutes + delta) % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY;
    onChange({ timeMinutes: next });
  };

  return (
    <View className="gap-4 rounded-2xl border-2 border-primary bg-primary-light p-4">
      <Text className="text-xl font-bold text-primary-dark">
        Slot {slot.id} · {api.getSlotColumnLabel(slot.id)}, {api.getSlotRowLabel(slot.id)}
      </Text>

      <View className="min-h-[44px] flex-row items-center justify-between">
        <Text className="text-lg text-slate-800">Aktifkan jadwal</Text>
        <Switch
          accessibilityLabel={`Aktifkan jadwal slot ${slot.id}`}
          value={slot.enabled}
          onValueChange={(enabled) =>
            onChange(enabled && slot.timeMinutes === null ? { enabled, timeMinutes: defaultTime } : { enabled })
          }
          trackColor={{ false: '#CBD5E1', true: PRIMARY }}
          thumbColor="#FFFFFF"
        />
      </View>

      <View className="gap-2">
        <Text className="text-lg text-slate-800">Waktu minum</Text>
        <View className="flex-row items-center justify-center gap-4">
          <Button label={`−${TIME_STEP_MINUTES}`} variant="outline" onPress={() => shiftTime(-TIME_STEP_MINUTES)} />
          <Text
            accessibilityLabel={`Waktu ${api.formatTime(slot.timeMinutes)}`}
            className="min-w-[120px] text-center text-4xl font-bold text-slate-900">
            {api.formatTime(slot.timeMinutes)}
          </Text>
          <Button label={`+${TIME_STEP_MINUTES}`} variant="outline" onPress={() => shiftTime(TIME_STEP_MINUTES)} />
        </View>
      </View>

      <View className="gap-2">
        <Text className="text-lg text-slate-800">Toleransi waktu</Text>
        <View className="flex-row flex-wrap gap-2">
          {TOLERANCE_OPTIONS.map((opt) => (
            <Chip
              key={opt.value}
              label={opt.label}
              selected={slot.toleranceMinutes === opt.value}
              onPress={() => onChange({ toleranceMinutes: opt.value })}
            />
          ))}
        </View>
      </View>

      <InfoRow label="Stok" value={`${slot.stock}/${slot.capacity} dosis`} />

      <Button label="Test Trigger" variant="outline" loading={testing} onPress={onTest} />
    </View>
  );
}

function ScheduleCard({
  draft,
  saved,
  selectedId,
  onSelect,
  onChangeSlot,
  testing,
  onTest,
  saving,
  onSave,
}: {
  draft: Slot[];
  saved: Slot[];
  selectedId: SlotId | null;
  onSelect: (id: SlotId) => void;
  onChangeSlot: (id: SlotId, patch: Partial<Slot>) => void;
  testing: boolean;
  onTest: (id: SlotId) => void;
  saving: boolean;
  onSave: () => void;
}) {
  const isChanged = (slot: Slot) => {
    const original = saved.find((s) => s.id === slot.id);
    return !original || !slotsEqual(original, slot);
  };
  const dirty = draft.some(isChanged);
  const selected = draft.find((s) => s.id === selectedId);

  return (
    <Card
      title="Kontrol Jadwal"
      right={
        dirty ? (
          <View className="rounded-full bg-amber-100 px-3 py-1">
            <Text className="text-base font-bold text-amber-800">Belum disimpan</Text>
          </View>
        ) : null
      }>
      {draft.length === 0 ? (
        <ActivityIndicator color={PRIMARY} />
      ) : (
        <View className="gap-3">
          <View className="flex-row gap-2">
            {COLUMNS.map((c) => (
              <Text key={c} className="flex-1 text-center text-base font-semibold text-slate-500">
                {c}
              </Text>
            ))}
          </View>
          {ROWS.map((row) => (
            <View key={row.key} className="gap-2">
              <Text className="text-lg font-semibold text-slate-700">
                {row.key} · {row.label}
              </Text>
              <View className="flex-row gap-2">
                {draft
                  .filter((s) => s.id.startsWith(row.key))
                  .map((slot) => (
                    <SlotCell
                      key={slot.id}
                      slot={slot}
                      selected={slot.id === selectedId}
                      changed={isChanged(slot)}
                      onPress={() => onSelect(slot.id)}
                    />
                  ))}
              </View>
            </View>
          ))}
        </View>
      )}

      {selected ? (
        <SlotEditor
          slot={selected}
          testing={testing}
          onChange={(patch) => onChangeSlot(selected.id, patch)}
          onTest={() => onTest(selected.id)}
        />
      ) : (
        draft.length > 0 && <Text className="text-lg text-slate-500">Ketuk salah satu slot untuk mengubah jadwal.</Text>
      )}

      <Button label="Simpan Jadwal ke Pillbox" loading={saving} disabled={draft.length === 0} onPress={onSave} />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------

export default function PillboxTestScreen() {
  const [now, setNow] = useState(() => Date.now());
  const [toast, setToast] = useState<ToastData | null>(null);

  const [device, setDevice] = useState<DeviceStatus | null>(null);
  const [connectionBusy, setConnectionBusy] = useState(false);
  // Backend mode only: the caregiver has no paired pillbox yet.
  const [needsPairing, setNeedsPairing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const [savedSlots, setSavedSlots] = useState<Slot[]>([]);
  const [draftSlots, setDraftSlots] = useState<Slot[]>([]);
  const [selectedSlotId, setSelectedSlotId] = useState<SlotId | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [alarmBusyId, setAlarmBusyId] = useState<string | null>(null);

  const [simSlotId, setSimSlotId] = useState<SlotId | null>(null);
  const [minutesLate, setMinutesLate] = useState(25);
  const [simBusy, setSimBusy] = useState<DoseEventType | null>(null);

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
        setNeedsPairing(false);
        setDevice(status);
        setSavedSlots(slots);
        setDraftSlots(slots);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof api.BackendError && err.code === 'NO_DEVICE') {
          setNeedsPairing(true);
          return;
        }
        const detail = err instanceof api.BackendError ? `: ${err.message}` : '';
        setToast(makeToast(`Gagal memuat data perangkat${detail}`, 'error'));
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  // New notifications go to the top of the list and trigger the banner.
  useEffect(
    () =>
      api.subscribeToNotifications((n) => {
        setNotifications((prev) => [n, ...prev]);
        setToast(makeToast(n.slotId ? `${n.title} · ${n.slotId}` : n.title, NOTIFICATION_STYLE[n.type].tone));
        setNow(Date.now());
      }),
    [],
  );

  // Backend mode: online/offline, battery and last sync change on the device side, so poll them.
  useEffect(() => {
    if (api.USE_MOCK || needsPairing) return;
    const timer = setInterval(() => {
      api.getDeviceStatus().then(setDevice).catch(() => undefined);
    }, 10_000);
    return () => clearInterval(timer);
  }, [needsPairing]);

  const handleConnected = (result: api.ConnectPillboxResult) => {
    showToast(result.joined ? 'Bergabung ke pillbox (mode pemantau)' : 'Pillbox berhasil dihubungkan', 'success');
    setReloadKey((k) => k + 1);
  };

  // Keeps relative times ("5 mnt lalu") fresh.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);

  const adherence = computeAdherence(notifications);
  const firstActiveSlot = savedSlots.find((s) => isSlotActive(s));
  const effectiveSimSlot =
    simSlotId && isSlotActive(savedSlots.find((s) => s.id === simSlotId)) ? simSlotId : (firstActiveSlot?.id ?? null);

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
      // The resulting notification arrives through the subscription above.
      await api.simulateDoseEvent({ slotId: effectiveSimSlot, type, minutesLate });
    } catch {
      showToast('Gagal mengirim event simulasi', 'error');
    } finally {
      setSimBusy(null);
    }
  };

  const markRead = (id: string) => {
    setNotifications((prev) => prev.map((n) => (n.id === id && !n.read ? { ...n, read: true } : n)));
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
    } catch (err) {
      // e.g. "Device is offline; the command was not sent" from the backend
      showToast(err instanceof api.BackendError ? `Gagal membunyikan alarm: ${err.message}` : 'Gagal membunyikan alarm', 'error');
    } finally {
      setAlarmBusyId(null);
    }
  };

  const handleChangeSlot = (id: SlotId, patch: Partial<Slot>) => {
    setDraftSlots((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  };

  const handleTestSlot = async (id: SlotId) => {
    setTesting(true);
    try {
      await api.triggerTestSlot(id);
      showToast(`Test trigger dikirim ke slot ${id}`, 'success');
    } catch {
      showToast('Gagal mengirim test trigger', 'error');
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const saved = await api.saveSchedule(draftSlots);
      setSavedSlots(saved);
      setDraftSlots(saved);
      if (device?.online) {
        setDevice(await api.getDeviceStatus());
        showToast('Jadwal berhasil disimpan ke Pillbox', 'success');
      } else {
        showToast('Jadwal disimpan, akan dikirim saat Pillbox online', 'warning');
      }
    } catch (err) {
      showToast(err instanceof api.BackendError ? `Gagal menyimpan jadwal: ${err.message}` : 'Gagal menyimpan jadwal', 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <View className="flex-1 bg-slate-100">
      <StatusBar style="dark" />
      <SafeAreaView style={{ flex: 1 }} edges={['top', 'left', 'right']}>
        <ScrollView contentContainerClassName="gap-5 px-4 pb-12 pt-4">
          <View className="gap-1">
            <Text className="text-3xl font-bold text-primary" accessibilityRole="header">
              Pillbox Lansia
            </Text>
            <Text className="text-lg text-slate-600">
              Mode uji · {api.USE_MOCK ? 'Data tiruan (mock)' : 'Backend'}
            </Text>
          </View>

          {needsPairing ? (
            <ConnectPillboxCard onConnected={handleConnected} />
          ) : (
            <>
              <AdherenceCard summary={adherence} />

              <ConnectionCard device={device} busy={connectionBusy} now={now} onToggle={handleToggleConnection} />

              {api.USE_MOCK && (
                <SimulatorCard
                  slots={savedSlots}
                  slotId={effectiveSimSlot}
                  onSelectSlot={setSimSlotId}
                  minutesLate={minutesLate}
                  onChangeMinutesLate={setMinutesLate}
                  busyType={simBusy}
                  onSimulate={handleSimulate}
                />
              )}

              <NotificationCenter
                notifications={notifications}
                filter={filter}
                onFilter={setFilter}
                now={now}
                alarmBusyId={alarmBusyId}
                onMarkRead={markRead}
                onCall={handleCall}
                onAlarm={handleAlarm}
              />

              <ScheduleCard
                draft={draftSlots}
                saved={savedSlots}
                selectedId={selectedSlotId}
                onSelect={(id) => setSelectedSlotId((current) => (current === id ? null : id))}
                onChangeSlot={handleChangeSlot}
                testing={testing}
                onTest={handleTestSlot}
                saving={saving}
                onSave={handleSave}
              />
            </>
          )}
        </ScrollView>
      </SafeAreaView>

      {toast && <Toast key={toast.id} toast={toast} onDone={hideToast} />}
    </View>
  );
}
