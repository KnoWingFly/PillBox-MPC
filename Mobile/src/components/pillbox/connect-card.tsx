import { useState, type ComponentProps } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';

import * as tokens from '@/theme/tokens';
import * as api from '@root/lib/api';

import { Button, Card, Icon, ScreenHeader } from './ui';

const CONNECT_ERRORS: Record<string, string> = {
  QR_CODE_NOT_RECOGNIZED: 'Kode perangkat tidak dikenal. Daftarkan dulu dari emulator (tombol "Daftarkan Perangkat").',
  DEVICE_PIN_INVALID: 'PIN harus 4 digit angka.',
  DEVICE_PIN_INCORRECT: 'PIN salah untuk pillbox yang sudah terpasang.',
  TOO_MANY_ATTEMPTS: 'Terlalu banyak percobaan PIN. Coba lagi beberapa menit lagi.',
  NETWORK_ERROR: 'Server tidak dapat dihubungi. Pastikan backend berjalan.',
};

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

/** Backend mode only: shown instead of the dashboard while the caregiver has no paired pillbox. */
export function ConnectPillboxScreen({ onConnected }: { onConnected: (result: api.ConnectPillboxResult) => void }) {
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
    <ScrollView contentContainerClassName="gap-4 px-4 pb-8 pt-4" keyboardShouldPersistTaps="handled">
      <ScreenHeader title="Hubungkan Pillbox" subtitle="Pasangkan Pillbox lansia ke akun Anda" />
      <View className="flex-row items-start gap-3 rounded-2xl bg-primary-light p-4">
        <Icon name="information-circle" size={22} color={tokens.colors.primary.dark} />
        <Text className="flex-1 text-body-sm text-primary-dark">
          Di emulator Smart Device, tekan &quot;Daftarkan Perangkat&quot; pada panel &quot;Koneksi Server&quot;, lalu ketik
          kode yang muncul di sini. Buat PIN 4 digit baru; jika pillbox sudah dipasangkan caregiver lain, masukkan PIN-nya
          untuk bergabung.
        </Text>
      </View>
      <Card>
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
        {error && (
          <View className="flex-row items-start gap-2" accessibilityRole="alert">
            <Icon name="alert-circle" size={18} color={tokens.colors.missed.fg} />
            <Text className="flex-1 text-body-sm font-semibold text-missed-fg">{error}</Text>
          </View>
        )}
        <Button label="Hubungkan" icon="link-outline" onPress={submit} loading={busy} disabled={!canSubmit} />
      </Card>
    </ScrollView>
  );
}
