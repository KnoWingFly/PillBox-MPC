import { useCallback, useState } from 'react';

import type { ToastTone } from '@/components/pillbox/helpers';
import { makeToast, Toast, type ToastData } from '@/components/pillbox/toast';

/**
 * Screen-local toast, web-safe (React Native's Alert.alert does nothing on web). Render `toastNode`
 * once at the end of the screen.
 */
export function useToast() {
  const [toast, setToast] = useState<ToastData | null>(null);
  const showToast = useCallback((text: string, tone: ToastTone) => setToast(makeToast(text, tone)), []);
  const hide = useCallback((id: number) => {
    setToast((current) => (current?.id === id ? null : current));
  }, []);
  const toastNode = toast ? <Toast key={toast.id} toast={toast} onDone={hide} /> : null;
  return { showToast, toastNode };
}
