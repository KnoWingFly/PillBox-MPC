import { useCallback, useEffect, useState } from 'react';

import { listPillboxes, type Pillbox } from '@root/lib/devices';

type PillboxOptions = {
  /** null while the first load runs. */
  pillboxes: Pillbox[] | null;
  loading: boolean;
  error: boolean;
  reload: () => void;
};

/** The caregiver's pillboxes (GET /devices) for the assignment section of the elderly form. */
export function usePillboxOptions(): PillboxOptions {
  const [pillboxes, setPillboxes] = useState<Pillbox[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    listPillboxes()
      .then((list) => {
        if (cancelled) return;
        setPillboxes(list);
        setError(false);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const reload = useCallback(() => {
    setLoading(true);
    setError(false);
    setAttempt((n) => n + 1);
  }, []);

  return { pillboxes, loading, error, reload };
}
