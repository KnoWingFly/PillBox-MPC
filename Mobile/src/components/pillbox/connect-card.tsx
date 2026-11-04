import { useRef, useState, type ComponentProps, type ReactNode } from 'react';
import { Pressable, ScrollView, Text, TextInput, View } from 'react-native';

import { AppConfig } from '@/config';
import { Strings } from '@/constants/strings';
import { errorMessage } from '@/lib/api/error-message';
import * as tokens from '@/theme/tokens';
import * as api from '@root/lib/api';
import * as devices from '@root/lib/devices';
import { PAIRING_CODE_HINT, parsePairingPayload } from '@root/lib/pairing-code';

import { QrScanner } from './qr-scanner';
import { Button, Card, Chip, Icon, IconBadge, ScreenHeader } from './ui';

const S = Strings.connect;

/** PIN length on the pillbox (backend device_pin). */
const PIN_LENGTH = 4;

/** Mapped through error-message.ts with pairing-specific wording; never the server's English text. */
function errorText(err: unknown, fallback: string): string {
  const text = errorMessage(err, S.errors);
  return text === Strings.common.unexpectedError ? fallback : text;
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

/** "Langkah 1 dari 2 • Pindai Perangkat". */
function StepPill({ label }: { label: string }) {
  return (
    <View className="flex-row items-center gap-2 self-start rounded-full bg-primary-light px-3 py-1.5">
      <View className="h-2 w-2 rounded-full bg-primary" />
      <Text className="text-body-sm font-semibold text-primary-dark">{label}</Text>
    </View>
  );
}

/** Dark viewfinder tile; tapping it opens the camera scanner. */
function ScanTile({ disabled, onPress }: { disabled: boolean; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={S.scanA11y}
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      className={`h-60 items-center justify-center gap-3 rounded-3xl bg-ink active:opacity-90 ${disabled ? 'opacity-60' : ''}`}>
      <View className="h-36 w-36 items-center justify-center gap-2 rounded-3xl border-2 border-primary-light/70">
        <Icon name="qr-code-outline" size={36} color={tokens.colors.surface.DEFAULT} />
        <Text className="text-caption font-semibold uppercase tracking-widest text-white/80">{S.scanFocus}</Text>
      </View>
      <View className="flex-row items-center gap-1.5 rounded-full bg-white/15 px-3 py-1.5">
        <Icon name="camera-outline" size={16} color={tokens.colors.surface.DEFAULT} />
        <Text className="text-body-sm font-semibold text-white">{S.scanTap}</Text>
      </View>
    </Pressable>
  );
}

/** "PB-1A2B3C4D Terdeteksi" banner, with an optional action on the right. */
function DetectedBanner({ code, right }: { code: string; right?: ReactNode }) {
  return (
    <View className="min-h-[52px] flex-row items-center gap-2 rounded-2xl bg-ontime-soft px-4 py-2">
      <Icon name="checkmark-circle-outline" size={22} color={tokens.colors.ontime.fg} />
      <Text className="flex-1 text-body font-bold text-ontime-fg" numberOfLines={1}>
        {S.detected(code)}
      </Text>
      {right}
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
  myDeviceIds,
  onUnhide,
  hiddenCount = 0,
  onCancel,
  onSignOut,
}: {
  onConnected: (result: devices.ConnectPillboxResult) => void;
  /** The pillbox with this code if it is already on the account (hidden ones included). */
  findExisting: (code: string) => ExistingPillbox | null;
  /** Every pillbox id on the account (from DevicesProvider), so the lookup needs no list request. */
  myDeviceIds: readonly string[];
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
  const [nickname, setNickname] = useState<string>(S.nicknameDefault);
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
        setNotice(S.unhidden(existing.name));
      } else setError(S.alreadyListed(existing.name));
      return;
    }
    inFlight.current = true;
    setBusy(true);
    try {
      const result = await devices.checkPairingCode(code, myDeviceIds);
      if (result.mode === 'pair') {
        const list = await devices.listPairableProfiles();
        setProfiles(list);
        setProfileId(list[0]?.id ?? null);
      }
      setCheck(result);
      setPin('');
    } catch (err) {
      setError(errorText(err, S.lookupFailed));
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

  const input = check
    ? { check, pin, nickname, elderly: profileId ? { id: profileId } : { newName: elderlyName } }
    : null;
  const inputProblem = input ? devices.connectInputProblem(input) : null;

  const submit = async () => {
    if (!input || inFlight.current) return;
    // Checked again here (Enter on the keyboard bypasses the disabled button): nothing is sent.
    if (inputProblem) {
      setError(errorText(inputProblem, S.connectFailed));
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      onConnected(await devices.connectPillbox(input));
    } catch (err) {
      // Someone else paired it between the lookup and now: go back so the next lookup offers "join".
      if (err instanceof api.BackendError && err.code === 'DEVICE_ALREADY_PAIRED') setCheck(null);
      setError(errorText(err, S.connectFailed));
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

  const canSubmit = input !== null && inputProblem === null;
  // A name that is too short is explained under the field once something was typed.
  const nameHint =
    check?.mode === 'pair' && profileId === null && elderlyName.trim() && inputProblem?.code === 'VALIDATION_ERROR'
      ? inputProblem.userMessage
      : null;

  return (
    <ScrollView contentContainerClassName="gap-4 px-4 pb-8 pt-4" keyboardShouldPersistTaps="handled">
      <ScreenHeader
        title={onCancel ? S.titleModal : S.titleEmpty}
        subtitle={onCancel ? S.subtitleModal : S.subtitleEmpty}
      />
      <StepPill label={check ? S.stepSecure : S.stepScan} />
      {!onCancel && hiddenCount > 0 && !check && (
        <Button label={S.showHidden(hiddenCount)} icon="eye-outline" variant="secondary" onPress={() => onUnhide('')} />
      )}
      {!check ? (
        <>
          <Card>
            <ScanTile disabled={busy} onPress={() => setScannerOpen(true)} />
            <Text className="text-center text-body-sm text-ink-muted">{S.scanHint}</Text>
            <ConnectInput
              label={S.manualLabel}
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
            {parsedCode && !error && !notice && <DetectedBanner code={parsedCode} />}
            {error && <ErrorRow text={error} />}
            {notice && (
              <View className="flex-row items-start gap-2" accessibilityRole="alert">
                <Icon name="checkmark-circle" size={18} color={tokens.colors.ontime.fg} />
                <Text className="flex-1 text-body-sm font-semibold text-ontime-fg">{notice}</Text>
              </View>
            )}
          </Card>
          <View className="flex-row items-start gap-3 rounded-3xl bg-primary-light p-4">
            <IconBadge icon="wifi" tone="primary" size="sm" />
            <View className="flex-1 gap-0.5">
              <Text className="text-body font-bold text-primary-dark">{S.tipsTitle}</Text>
              <Text className="text-body-sm text-primary-dark">{S.tipsText}</Text>
            </View>
          </View>
          <Button
            label={error ? S.retry : S.next}
            icon={error ? 'refresh' : 'arrow-forward'}
            onPress={() => parsedCode && void lookUp(parsedCode)}
            loading={busy}
            disabled={!parsedCode}
          />
        </>
      ) : (
        <Card>
          <DetectedBanner code={check.code} right={<Button label={S.changeCode} size="sm" variant="ghost" onPress={changeCode} disabled={busy} />} />
          {check.mode === 'join' ? (
            <View className="flex-row items-start gap-3 rounded-2xl bg-late-soft p-4">
              <Icon name="people-outline" size={22} color={tokens.colors.late.fg} />
              <Text className="flex-1 text-body-sm text-late-fg">{S.joinNotice(check.elderlyName)}</Text>
            </View>
          ) : (
            <Text className="text-body-sm text-ink-muted">{S.pairNotice}</Text>
          )}
          <ConnectInput
            label={check.mode === 'join' ? S.pinJoin : S.pinNew}
            value={pin}
            onChangeText={(v) => setPin(v.replace(/\D/g, '').slice(0, PIN_LENGTH))}
            placeholder={S.pinPlaceholder}
            keyboardType="number-pad"
            secureTextEntry
            maxLength={PIN_LENGTH}
            onSubmitEditing={() => canSubmit && void submit()}
            editable={!busy}
          />
          {check.mode === 'pair' && (
            <>
              <ConnectInput
                label={S.nickname}
                value={nickname}
                onChangeText={setNickname}
                maxLength={devices.PILLBOX_NAME_MAX}
                editable={!busy}
              />
              <View className="gap-1.5">
                <Text className="text-body-sm font-semibold text-ink">{S.forElderly}</Text>
                <View className="flex-row flex-wrap gap-2">
                  {(profiles ?? []).map((p) => (
                    <Chip key={p.id} label={p.name} selected={profileId === p.id} onPress={() => setProfileId(p.id)} disabled={busy} />
                  ))}
                  <Chip label={S.newProfile} selected={profileId === null} onPress={() => setProfileId(null)} disabled={busy} />
                </View>
              </View>
              {profileId === null && (
                <ConnectInput
                  label={S.elderlyName}
                  value={elderlyName}
                  onChangeText={setElderlyName}
                  placeholder={S.elderlyNamePlaceholder}
                  maxLength={AppConfig.elderlyNameMaxLength}
                  editable={!busy}
                />
              )}
              {nameHint && <Text className="text-caption text-ink-muted">{nameHint}</Text>}
            </>
          )}
          {error && <ErrorRow text={error} />}
          <Button
            label={check.mode === 'join' ? S.join : S.pair}
            icon="link-outline"
            onPress={submit}
            loading={busy}
            disabled={!canSubmit}
          />
        </Card>
      )}
      {api.IS_SECURE_CONNECTION && (
        <View className="flex-row items-center justify-center gap-1.5">
          <Icon name="shield-checkmark-outline" size={16} color={tokens.colors.ink.muted} />
          <Text className="text-caption text-ink-muted">{S.secureNote}</Text>
        </View>
      )}
      {onCancel && <Button label={S.cancel} variant="ghost" onPress={onCancel} disabled={busy} />}
      {onSignOut && <Button label={S.signOut} icon="log-out-outline" variant="ghost" onPress={onSignOut} disabled={busy} />}
      {scannerOpen && <QrScanner onScanned={onScanned} onClose={() => setScannerOpen(false)} />}
    </ScrollView>
  );
}
