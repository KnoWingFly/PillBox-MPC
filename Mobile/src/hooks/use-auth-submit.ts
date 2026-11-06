import { useRef, useState } from 'react';

import { useAuth } from '@/hooks/use-auth';
import { useToast } from '@/hooks/use-toast';
import { errorMessage } from '@/lib/api/error-message';

/**
 * Shared submit flow for the auth forms: validate, then run the request with a busy flag and show
 * a validation or API error as a toast (works on web too). On success the auth gate swaps the
 * screen out. Render `toastNode` in the screen.
 */
export function useAuthSubmit() {
  const { clearSessionNotice } = useAuth();
  const [loading, setLoading] = useState(false);
  // A second tap (or Enter) before the first request settles is ignored.
  const inFlight = useRef(false);
  const { showToast, toastNode } = useToast();

  async function submit(problem: string | null, action: () => Promise<unknown>) {
    if (inFlight.current) return;
    if (problem) {
      showToast(problem, 'error');
      return;
    }
    inFlight.current = true;
    setLoading(true);
    try {
      clearSessionNotice();
      await action();
    } catch (err) {
      showToast(errorMessage(err), 'error');
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }

  return { loading, submit, showToast, toastNode };
}
