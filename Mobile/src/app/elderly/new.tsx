import { useRouter } from 'expo-router';
import { useCallback, useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ElderlyIdentitySection } from '@/components/elderly/elderly-identity-section';
import { PillboxAssignSection } from '@/components/elderly/pillbox-assign-section';
import { makeToast, Toast, type ToastData } from '@/components/pillbox/toast';
import { Button } from '@/components/pillbox/ui';
import { BackHeader } from '@/components/ui/back-header';
import { Strings } from '@/constants/strings';
import { useCreateElderly } from '@/hooks/use-create-elderly';
import { usePillboxOptions } from '@/hooks/use-pillbox-options';

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
  const busy = form.submitting !== null || leaving;

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
    if (result.ok) router.replace({ pathname: '/elderly/[id]/schedule', params: { id: result.elderly.id } });
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
      {toast && <Toast key={toast.id} toast={toast} onDone={onToastDone} />}
    </SafeAreaView>
  );
}
