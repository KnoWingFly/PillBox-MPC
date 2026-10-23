import { useRef, useState, type ComponentProps } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';

import * as tokens from '@/theme/tokens';
import * as api from '@root/lib/api';
import * as devices from '@root/lib/devices';
import { PAIRING_CODE_HINT, parsePairingPayload } from '@root/lib/pairing-code';

import { QrScanner } from './qr-scanner';
import { Button, Card, Chip, Icon, ScreenHeader } from './ui';

const CONNECT_ERRORS: Record<string, string> = {
  QR_CODE_NOT_RECOGNIZED: 'Kode tidak dikenal server. Pastikan pillbox sudah menekan "Daftarkan Perangkat" di panel "Koneksi Server".',
  DEVICE_ALREADY_MINE: 'Pillbox ini sudah terhubung ke akun Anda.',
  DEVICE_ALREADY_PAIRED: 'Pillbox ini baru saja dipasangkan akun lain. Periksa kode lagi untuk bergabung dengan PIN-nya.',
  DEVICE_PIN_INVALID: 'PIN harus 4 digit angka.',
  DEVICE_PIN_INCORRECT: 'PIN salah untuk pillbox yang sudah terpasang.',
  TOO_MANY_ATTEMPTS: 'Terlalu banyak percobaan. Coba lagi beberapa menit lagi.',
  NETWORK_ERROR: 'Server tidak dapat dihubungi. Periksa koneksi internet Anda, lalu coba lagi.',
};

function errorText(err: unknown, fallback: string): string {
  return err instanceof api.BackendError ? (CONNECT_ERRORS[err.code] ?? err.message) : fallback;
}

function ConnectInput({ label, ...props }: { label: string } & ComponentProps<typeof TextInput>) {
  return (
    <View className="gap-1.5">
      <Text className="text-body-sm font-semibold text-ink">{label}</Text>
      <TextInput
        className="min-h-[52px] rounded-2xl border border-line-strong bg-surface px-4 text-body text-ink"
        placeholderTextColor={tokens.colors.ink.subtle}
        autoCorrect={false}
        accessibilityLabel={label}
        {...props}
      />
    </View>
  );
}

function ErrorRow({ text }: { text: string }) {
  return (
    <View className="flex-row items-start gap-2" accessibilityRole="alert">
      <Icon name="alert-circle" size={18} color={tokens.colors.missed.fg} />
      <Text className="flex-1 text-body-sm font-semibold text-missed-fg">{text}</Text>
    </View>
  );
}

/** How the code relates to the caregiver's own list, checked locally before any request. */
export type ExistingPillbox = { id: string; name: string; hidden: boolean };

/**
 * Pair or join a pillbox: step 1 code (typed or scanned) -> lookup; step 2 PIN, name, elderly.
 * Used full screen when the caregiver has no pillbox, and in a modal from "Tambah pillbox".
 */
export function ConnectPillboxScreen({
  onConnected,
  findExisting,
  onUnhide,
  hiddenCount = 0,
  onCancel,
  onSignOut,
}: {
  onConnected: (result: devices.ConnectPillboxResult) => void;
  /** The pillbox with this code if it is already on the account (hidden ones included). */
  findExisting: (code: string) => ExistingPillbox | null;
  onUnhide: (id: string) => void;
  /** Full-screen mode: pillboxes hidden on this phone, offered back so the caregiver is never stuck. */
  hiddenCount?: number;
  /** Modal mode: shows "Batal". */
  onCancel?: () => void;
  /** Full-screen mode: lets a caregiver without a pillbox still sign out. */
  onSignOut?: () => void;
}) {
  const [deviceCode, setDeviceCode] = useState('');
  const [check, setCheck] = useState<devices.PairingCheck | null>(null);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [pin, setPin] = useState('');
  const [nickname, setNickname] = useState('Pillbox Lansia');
  const [profiles, setProfiles] = useState<devices.ElderlyProfile[] | null>(null);
  /** Selected elderly profile id; null = create a new profile named `elderlyName`. */
  const [profileId, setProfileId] = useState<string | null>(null);
  const [elderlyName, setElderlyName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Guards against a second lookup (double tap, or a scan landing while one is in flight).
  const inFlight = useRef(false);

  const parsedCode = parsePairingPayload(deviceCode);
  const formatError = deviceCode.trim() && !parsedCode ? PAIRING_CODE_HINT : null;

  const lookUp = async (code: string) => {
    if (inFlight.current) return;
    setError(null);
    setNotice(null);
    // Same pillbox twice: answered from the local list, nothing is sent.
    const existing = findExisting(code);
    if (existing) {
      if (existing.hidden) {
        onUnhide(existing.id);
        setNotice(`"${existing.name}" sudah ada di akun Anda dan sekarang ditampilkan lagi.`);
      } else setError(`Pillbox ini sudah ada di daftar Anda ("${existing.name}").`);
      return;
    }
    inFlight.current = true;
    setBusy(true);
    try {
      const result = await devices.checkPairingCode(code);
      if (result.mode === 'pair') {
        const list = await devices.listPairableProfiles();
        setProfiles(list);
        setProfileId(list[0]?.id ?? null);
      }
      setCheck(result);
      setPin('');
    } catch (err) {
      setError(errorText(err, 'Gagal memeriksa kode pillbox.'));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const onScanned = (code: string) => {
    setScannerOpen(false);
    setDeviceCode(code);
    void lookUp(code);
  };

  const submit = async () => {
    if (!check || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      onConnected(
        await devices.connectPillbox({
          check,
          pin,
          nickname,
          elderly: profileId ? { id: profileId } : { newName: elderlyName },
        }),
      );
    } catch (err) {
      // Someone else paired it between the lookup and now: go back so the next lookup offers "join".
      if (err instanceof api.BackendError && err.code === 'DEVICE_ALREADY_PAIRED') setCheck(null);
      setError(errorText(err, 'Gagal menghubungkan pillbox.'));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const changeCode = () => {
    setCheck(null);
    setPin('');
    setError(null);
  };

  const canSubmit = /^\d{4}$/.test(pin) && (check?.mode === 'join' || profileId !== null || elderlyName.trim().length > 0);

  return (
    <ScrollView contentContainerClassName="gap-4 px-4 pb-8 pt-4" keyboardShouldPersistTaps="handled">
      <ScreenHeader
        title={onCancel ? 'Tambah Pillbox' : 'Belum ada pillbox'}
        subtitle={onCancel ? 'Pasangkan Pillbox lansia ke akun Anda' : 'Tambahkan pillbox lansia untuk mulai memantau jadwal minum obat.'}
      />
      {!onCancel && hiddenCount > 0 && !check && (
        <Button
          label={`Tampilkan ${hiddenCount} pillbox tersembunyi`}
          icon="eye-outline"
          variant="secondary"
          onPress={() => onUnhide('')}
        />
      )}
      {!check ? (
        <>
          <View className="flex-row items-start gap-3 rounded-2xl bg-primary-light p-4">
            <Icon name="information-circle" size={22} color={tokens.colors.primary.dark} />
            <Text className="flex-1 text-body-sm text-primary-dark">
              Di pillbox, buka panel &quot;Koneksi Server&quot;. Pindai QR yang tampil, atau ketik kodenya.
            </Text>
          </View>
          <Card>
            <Button label="Pindai QR" icon="qr-code-outline" onPress={() => setScannerOpen(true)} disabled={busy} />
            <ConnectInput
              label="Atau ketik kode perangkat"
              value={deviceCode}
              onChangeText={(v) => {
                setDeviceCode(v);
                setError(null);
                setNotice(null);
              }}
              placeholder="PB-1A2B3C4D"
              autoCapitalize="characters"
              maxLength={64}
              editable={!busy}
              onSubmitEditing={() => parsedCode && void lookUp(parsedCode)}
            />
            {formatError && <Text className="text-caption text-ink-muted">{formatError}</Text>}
            {error && <ErrorRow text={error} />}
            {notice && (
              <View className="flex-row items-start gap-2" accessibilityRole="alert">
                <Icon name="checkmark-circle" size={18} color={tokens.colors.ontime.fg} />
                <Text className="flex-1 text-body-sm font-semibold text-ontime-fg">{notice}</Text>
              </View>
            )}
            <Button
              label={error ? 'Coba lagi' : 'Lanjut'}
              icon={error ? 'refresh' : 'arrow-forward'}
              variant={parsedCode ? 'primary' : 'secondary'}
              onPress={() => parsedCode && void lookUp(parsedCode)}
              loading={busy}
              disabled={!parsedCode}
            />
          </Card>
        </>
      ) : (
        <Card>
          <View className="flex-row items-center justify-between">
            <Text className="text-body font-semibold text-ink">{check.code}</Text>
            <Button label="Ganti kode" size="sm" variant="ghost" onPress={changeCode} disabled={busy} />
          </View>
          {check.mode === 'join' ? (
            <View className="flex-row items-start gap-3 rounded-2xl bg-late-soft p-4">
              <Icon name="people-outline" size={22} color={tokens.colors.late.fg} />
              <Text className="flex-1 text-body-sm text-late-fg">
                Pillbox ini sudah terhubung ke akun pengasuh lain
                {check.elderlyName ? ` (lansia: ${check.elderlyName})` : ''}. Masukkan PIN-nya untuk bergabung
                sebagai pemantau: Anda bisa melihat jadwal dan notifikasi, tetapi tidak bisa mengubahnya.
              </Text>
            </View>
          ) : (
            <Text className="text-body-sm text-ink-muted">Pillbox baru. Buat PIN 4 digit untuk mengamankannya.</Text>
          )}
          <ConnectInput
            label={check.mode === 'join' ? 'PIN pillbox (4 digit)' : 'Buat PIN baru (4 digit)'}
            value={pin}
            onChangeText={(v) => setPin(v.replace(/\D/g, '').slice(0, 4))}
            placeholder="1234"
            keyboardType="number-pad"
            secureTextEntry
            maxLength={4}
            editable={!busy}
          />
          {check.mode === 'pair' && (
            <>
              <ConnectInput
                label="Nama pillbox"
                value={nickname}
                onChangeText={setNickname}
                maxLength={devices.PILLBOX_NAME_MAX}
                editable={!busy}
              />
              <View className="gap-1.5">
                <Text className="text-body-sm font-semibold text-ink">Untuk lansia</Text>
                <View className="flex-row flex-wrap gap-2">
                  {(profiles ?? []).map((p) => (
                    <Chip key={p.id} label={p.name} selected={profileId === p.id} onPress={() => setProfileId(p.id)} disabled={busy} />
                  ))}
                  <Chip label="+ Profil baru" selected={profileId === null} onPress={() => setProfileId(null)} disabled={busy} />
                </View>
              </View>
              {profileId === null && (
                <ConnectInput
                  label="Nama lansia"
                  value={elderlyName}
                  onChangeText={setElderlyName}
                  placeholder="mis. Oma Sari"
                  maxLength={devices.PILLBOX_NAME_MAX}
                  editable={!busy}
                />
              )}
            </>
          )}
          {error && <ErrorRow text={error} />}
          <Button
            label={check.mode === 'join' ? 'Bergabung' : 'Hubungkan'}
            icon="link-outline"
            onPress={submit}
            loading={busy}
            disabled={!canSubmit}
          />
        </Card>
      )}
      {onCancel && <Button label="Batal" variant="ghost" onPress={onCancel} disabled={busy} />}
      {onSignOut && <Button label="Keluar dari akun" icon="log-out-outline" variant="ghost" onPress={onSignOut} disabled={busy} />}
      {scannerOpen && <QrScanner onScanned={onScanned} onClose={() => setScannerOpen(false)} />}
    </ScrollView>
  );
}
