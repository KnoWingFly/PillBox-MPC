// Full-screen QR scanner for pairing codes. Only a payload that passes parsePairingPayload is
// handed to the caller; anything else stays on the phone and shows an inline hint.
import { CameraView, useCameraPermissions, type BarcodeScanningResult } from 'expo-camera';
import * as Linking from 'expo-linking';
import { useCallback, useRef, useState } from 'react';
import { Modal, Platform, Pressable, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { parsePairingPayload } from '@root/lib/pairing-code';

import { Button, Icon } from './ui';

/** The same foreign QR is reported at most this often while it stays in view. */
const INVALID_REPEAT_MS = 2000;

const isWeb = Platform.OS === 'web';
// getUserMedia (the web camera) only exists on https:// and http://localhost.
const webCameraBlocked = isWeb && typeof window !== 'undefined' && window.isSecureContext === false;

function PermissionView({
  canAskAgain,
  onRequest,
  onManual,
}: {
  canAskAgain: boolean;
  onRequest: () => void;
  onManual: () => void;
}) {
  return (
    <View className="flex-1 items-center justify-center gap-4 px-6">
      <Icon name="camera-outline" size={48} color="#FFFFFF" />
      <Text className="text-center text-title font-semibold text-white">Izin kamera diperlukan</Text>
      <Text className="text-center text-body-sm text-white/80">
        {canAskAgain
          ? 'Kamera dipakai hanya untuk memindai kode QR di panel "Koneksi Server" pillbox.'
          : isWeb
            ? 'Akses kamera diblokir. Izinkan kamera lewat ikon gembok di bilah alamat browser, lalu muat ulang halaman.'
            : 'Akses kamera ditolak. Aktifkan izin kamera untuk PillCare di Pengaturan.'}
      </Text>
      {canAskAgain ? (
        <Button label="Izinkan Kamera" icon="camera-outline" onPress={onRequest} />
      ) : (
        !isWeb && <Button label="Buka Pengaturan" icon="settings-outline" onPress={() => void Linking.openSettings()} />
      )}
      <Button label="Ketik kode manual" icon="keypad-outline" variant="secondary" onPress={onManual} />
    </View>
  );
}

/** Mount it only while scanning: each mount starts unlocked with the torch off. */
export function QrScanner({
  onScanned,
  onClose,
}: {
  /** Called once per mount, with a validated device code. */
  onScanned: (code: string) => void;
  /** Closes the scanner without a code (the caller falls back to manual entry). */
  onClose: () => void;
}) {
  const [permission, requestPermission] = useCameraPermissions();
  const [torch, setTorch] = useState(false);
  const [invalidHint, setInvalidHint] = useState<string | null>(null);
  const [mountError, setMountError] = useState<string | null>(null);
  // Barcode callbacks fire many times per second while a code is in view: the lock makes the
  // first valid scan the only one, even before React re-renders.
  const lockedRef = useRef(false);
  const lastInvalidRef = useRef<{ data: string; at: number } | null>(null);

  const handleScan = useCallback(
    ({ data }: BarcodeScanningResult) => {
      if (lockedRef.current) return;
      const code = parsePairingPayload(data);
      if (code) {
        lockedRef.current = true;
        setTorch(false);
        onScanned(code);
        return;
      }
      const now = Date.now();
      const last = lastInvalidRef.current;
      if (last && last.data === data && now - last.at < INVALID_REPEAT_MS) return;
      lastInvalidRef.current = { data, at: now };
      setInvalidHint('QR ini bukan kode pillbox PillCare. Arahkan ke QR di panel "Koneksi Server".');
    },
    [onScanned],
  );

  const granted = permission?.granted === true;

  return (
    <Modal visible animationType="slide" onRequestClose={onClose} presentationStyle="fullScreen">
      <SafeAreaView style={{ flex: 1, backgroundColor: '#000' }}>
        <View className="flex-row items-center justify-between px-4 py-3">
          <Text className="text-title font-semibold text-white">Pindai QR Pillbox</Text>
          <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Tutup pemindai" hitSlop={12}>
            <Icon name="close" size={28} color="#FFFFFF" />
          </Pressable>
        </View>

        {webCameraBlocked ? (
          <View className="flex-1 items-center justify-center gap-4 px-6">
            <Text className="text-center text-body-sm text-white/80">
              Kamera di browser hanya berfungsi lewat https:// atau localhost. Ketik kode secara manual.
            </Text>
            <Button label="Ketik kode manual" icon="keypad-outline" variant="secondary" onPress={onClose} />
          </View>
        ) : !permission ? (
          <View className="flex-1" />
        ) : !granted ? (
          <PermissionView canAskAgain={permission.canAskAgain} onRequest={() => void requestPermission()} onManual={onClose} />
        ) : mountError ? (
          <View className="flex-1 items-center justify-center gap-4 px-6">
            <Icon name="alert-circle" size={40} color="#FCA5A5" />
            <Text className="text-center text-body-sm text-white/80">{mountError}</Text>
            <Button label="Coba lagi" icon="refresh" onPress={() => setMountError(null)} />
            <Button label="Ketik kode manual" icon="keypad-outline" variant="secondary" onPress={onClose} />
          </View>
        ) : (
          <View className="flex-1">
            <CameraView
              style={{ flex: 1 }}
              facing="back"
              active
              enableTorch={torch}
              barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
              onBarcodeScanned={handleScan}
              onMountError={() => setMountError('Kamera tidak dapat dibuka. Pastikan tidak dipakai aplikasi lain.')}
            />
            {/* Viewfinder frame */}
            <View pointerEvents="none" className="absolute inset-0 items-center justify-center">
              <View className="h-64 w-64 rounded-3xl border-4 border-white/90" />
            </View>
            <View className="absolute bottom-0 left-0 right-0 gap-3 bg-black/60 px-4 pb-6 pt-4">
              <Text className="text-center text-body-sm text-white" accessibilityLiveRegion="polite">
                {invalidHint ?? 'Arahkan kamera ke QR di panel "Koneksi Server" pada pillbox.'}
              </Text>
              <View className="flex-row justify-center gap-3">
                <Button
                  label={torch ? 'Senter: Nyala' : 'Senter: Mati'}
                  icon={torch ? 'flashlight' : 'flashlight-outline'}
                  variant="secondary"
                  onPress={() => setTorch((t) => !t)}
                />
                <Button label="Ketik manual" icon="keypad-outline" variant="secondary" onPress={onClose} />
              </View>
            </View>
          </View>
        )}
      </SafeAreaView>
    </Modal>
  );
}
