import { useCallback, useRef, useState } from 'react';

import { AppConfig } from '@/config';
import { usePolling } from '@/hooks/use-polling';
import * as api from '@root/lib/api';

/**
 * checking = waiting for the pillbox to report the saved schedule as applied;
 * applied   = the pillbox runs it (config_version_applied caught up with config_version);
 * waiting   = not confirmed within AppConfig.configSyncTimeoutMs (e.g. pillbox offline): it is saved
 *             on the server and the pillbox picks it up when it reconnects.
 */
export type ConfigSyncState = 'checking' | 'applied' | 'waiting';

/** Polls the active pillbox's applied config version after a schedule save. Mount once per save. */
export function useConfigSync(): ConfigSyncState {
  const [state, setState] = useState<ConfigSyncState>('checking');
  const startedAt = useRef<number | null>(null);

  const check = useCallback(async () => {
    startedAt.current ??= Date.now();
    try {
      const sync = await api.getConfigSync();
      if (sync.applied !== null && sync.applied >= sync.version) {
        setState('applied');
        return;
      }
    } catch {
      // keep trying until the deadline: a missed answer is not a failed sync
    }
    if (Date.now() - startedAt.current >= AppConfig.configSyncTimeoutMs) setState('waiting');
  }, []);

  usePolling(check, state === 'checking' ? AppConfig.configSyncPollMs : null, { immediate: true });
  return state;
}
