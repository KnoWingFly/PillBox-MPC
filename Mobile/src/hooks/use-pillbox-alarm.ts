import { useCallback, useEffect, useState } from 'react';

import * as api from '@root/lib/api';

/**
 * The alarm a caregiver started on the active pillbox ("Bunyikan Alarm", "Tes Pengingat"). It rings
 * for a known time (AppConfig); until then the app offers to stop it (DELETE /devices/{id}/alarm).
 */
export function usePillboxAlarm() {
  const [ringingUntil, setRingingUntil] = useState<number | null>(null);
  const [stopping, setStopping] = useState(false);

  // Forget the alarm once the pillbox has stopped on its own.
  useEffect(() => {
    if (ringingUntil === null) return;
    const timer = setTimeout(() => setRingingUntil(null), Math.max(0, ringingUntil - Date.now()));
    return () => clearTimeout(timer);
  }, [ringingUntil]);

  /** Call after the pillbox acked the alarm. */
  const started = useCallback((durationSeconds: number) => {
    setRingingUntil(Date.now() + durationSeconds * 1000);
  }, []);

  /** Stops it on the pillbox; throws when the request fails (the alarm is then still ringing). */
  const stop = useCallback(async () => {
    setStopping(true);
    try {
      await api.stopAlarm();
      setRingingUntil(null);
    } finally {
      setStopping(false);
    }
  }, []);

  return { ringing: ringingUntil !== null, stopping, started, stop };
}
