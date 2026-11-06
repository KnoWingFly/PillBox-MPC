import { useRouter } from 'expo-router';
import { useCallback, useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ElderlySavedSheet } from '@/components/elderly/elderly-saved-sheet';
import { ElderlyIdentitySection } from '@/components/elderly/elderly-identity-section';
import { PillboxAssignSection } from '@/components/elderly/pillbox-assign-section';
import { makeToast, Toast, type ToastData } from '@/components/pillbox/toast';
import { Button, StatusPill } from '@/components/pillbox/ui';
import { BackHeader } from '@/components/ui/back-header';
import { Strings } from '@/constants/strings';
import { useCreateElderly } from '@/hooks/use-create-elderly';
import { usePillboxOptions } from '@/hooks/use-pillbox-options';
import type { ElderlyFormValues } from '@/lib/elderly-form';

const S = Strings.elderlyForm;

/** "Tambah Profil Lansia". The caregiver becomes OWNER; pillboxes are paired after saving. */
export default function NewElderlyScreen() {
  const router = useRouter();
  const form = useCreateElderly();
  const pillboxes = usePillboxOptions();
  const [toast, setToast] = useState<ToastData | null>(null);
  // Draft saved: stay until its toast has been read, then go back. A ref keeps onToastDone stable
  // (Toast restarts its animation when onDone changes).
  const leavingRef = useRef(false);
  const [leaving, setLeaving] = useState(false);
  /**
   * Complete save done: the success sheet shows these values until the caregiver picks a way out.
   * `phone` is the number as the server stored it (normalized to E.164), not what was typed.
   */
  const [saved, setSaved] = useState<{ id: string; values: ElderlyFormValues; phone: string | null } | null>(null);
  const busy = form.submitting !== null || leaving || saved !== null;

  const goBack = useCallback(() => {
    if (router.canGoBack()) router.back();
    else router.replace('/');
  }, [router]);

  const onToastDone = useCallback(
    (id: number) => {
      setToast((current) => (current?.id === id ? null : current));
      if (leavingRef.current) goBack();
    },
    [goBack],
  );

  const saveComplete = async () => {
    const result = await form.save('complete');
    if (!result) return;
    if (result.ok) setSaved({ id: result.elderly.id, values: form.values, phone: result.elderly.contact_phone });
    else setToast(makeToast(result.message, 'error'));
  };

  const saveDraft = async () => {
    const result = await form.save('draft');
    if (!result) return;
    if (result.ok) {
      leavingRef.current = true;
      setLeaving(true);
      setToast(makeToast(S.draftSaved, 'success'));
    } else {
      setToast(makeToast(result.message, 'error'));
    }
  };

  return (
    <SafeAreaView className="flex-1 bg-canvas" edges={['top', 'left', 'right', 'bottom']}>
      <BackHeader title={S.title} onBack={goBack} />
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} className="flex-1">
        <ScrollView contentContainerClassName="gap-4 px-4 pb-8 pt-4" keyboardShouldPersistTaps="handled">
          <View className="gap-2">
            <View className="self-start">
              <StatusPill label={S.badge} tone="primary" icon="heart" />
            </View>
            <Text className="text-body-sm text-ink-muted">{S.intro}</Text>
          </View>
          <ElderlyIdentitySection values={form.values} errors={form.errors} onChange={form.setField} required />
          <PillboxAssignSection
            pillboxes={pillboxes.pillboxes}
            loading={pillboxes.loading}
            error={pillboxes.error}
            onRetry={pillboxes.reload}
            onPairNew={() => setToast(makeToast(S.comingSoon, 'info'))}
          />
          <View className="gap-3">
            <Button
              label={S.submitComplete}
              icon="save-outline"
              onPress={saveComplete}
              loading={form.submitting === 'complete'}
              disabled={busy}
            />
            <Button
              label={S.submitDraft}
              variant="secondary"
              onPress={saveDraft}
              loading={form.submitting === 'draft'}
              disabled={busy}
            />
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
      <ElderlySavedSheet
        values={saved?.values ?? null}
        phone={saved?.phone ?? null}
        // Schedules live on the pillbox: open the dashboard's schedule tab (`at` makes a repeat count).
        onSchedule={() => router.dismissTo({ pathname: '/', params: { tab: 'schedule', at: String(Date.now()) } })}
        onHome={() => router.dismissTo('/')}
      />
      {toast && <Toast key={toast.id} toast={toast} onDone={onToastDone} />}
    </SafeAreaView>
  );
}
