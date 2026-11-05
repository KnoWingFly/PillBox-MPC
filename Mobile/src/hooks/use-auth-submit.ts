import { useState } from 'react';
import { Alert } from 'react-native';

import { Strings } from '@/constants/strings';
import { useAuth } from '@/hooks/use-auth';
import { errorMessage } from '@/lib/api/error-message';

/**
 * Shared submit flow for the auth forms: validate, then run the request with a busy flag and show
 * a validation or API error in an alert. On success the auth gate swaps the screen out.
 */
export function useAuthSubmit() {
  const { clearSessionNotice } = useAuth();
  const [loading, setLoading] = useState(false);

  async function submit(problem: string | null, action: () => Promise<unknown>) {
    if (problem) {
      Alert.alert(Strings.common.error, problem);
      return;
    }
    setLoading(true);
    try {
      clearSessionNotice();
      await action();
    } catch (err) {
      Alert.alert(Strings.common.error, errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return { loading, submit };
}
