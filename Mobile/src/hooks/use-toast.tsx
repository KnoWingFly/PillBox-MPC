import { useCallback, useState } from 'react';

import type { ToastTone } from '@/components/pillbox/helpers';
import { makeToast, Toast, type ToastData } from '@/components/pillbox/toast';

/**
 * Screen-local toast, web-safe (React Native's Alert.alert does nothing on web). Render `toastNode`
 * once at the end of the screen. `initial` shows a toast as the screen opens (e.g. a result the
 * previous screen could not show because it navigated here).
 */
export function useToast(initial?: { text: string; tone: ToastTone } | null) {
  const [toast, setToast] = useState<ToastData | null>(() => (initial ? makeToast(initial.text, initial.tone) : null));
  const showToast = useCallback((text: string, tone: ToastTone) => setToast(makeToast(text, tone)), []);
  const hide = useCallback((id: number) => {
    setToast((current) => (current?.id === id ? null : current));
  }, []);
  const toastNode = toast ? <Toast key={toast.id} toast={toast} onDone={hide} /> : null;
  return { showToast, toastNode };
}
