import { useCallback, useEffect, useRef, useState } from 'react';

import {
  calibrateDeviceClock,
  getDeviceClock,
  getElderlyDetail,
  getNotificationPreferences,
  getTodayDoses,
  getWeekMissed,
  saveNotificationPreferences,
  setAutoSyncTimezone,
  type DeviceClock,
  type ElderlyDetail,
  type NotificationPreferences,
  type PreferenceToggle,
  type TodayDose,
  type WeekMissed,
} from '@root/lib/insights';

/**
 * Data the redesigned tabs show besides status and schedules: today's doses, the weekly missed
 * chart, the elderly profile, the pillbox clock and notification preferences. The dashboard is
 * remounted per pillbox, so this hook belongs to one pillbox. `dayMs` is "now" on the pillbox clock.
 */
export function useDashboardInsights(dayMs: number, enabled: boolean) {
  const [todayDoses, setTodayDoses] = useState<TodayDose[] | null>(null);
  const [dosesError, setDosesError] = useState(false);
  const [week, setWeek] = useState<WeekMissed | null>(null);
  const [elderly, setElderly] = useState<ElderlyDetail | null>(null);
  const [clock, setClock] = useState<DeviceClock | null>(null);
  const [prefs, setPrefs] = useState<NotificationPreferences | null>(null);
  const [prefsBusy, setPrefsBusy] = useState<PreferenceToggle | null>(null);
  // Read inside callbacks without re-creating them each tick of the pillbox clock.
  const dayRef = useRef(dayMs);
  useEffect(() => {
    dayRef.current = dayMs;
  }, [dayMs]);

  const refreshDoses = useCallback(() => {
    getTodayDoses(dayRef.current)
      .then((doses) => {
        setTodayDoses(doses);
        setDosesError(false);
      })
      .catch(() => setDosesError(true));
    getWeekMissed(dayRef.current)
      .then(setWeek)
      .catch(() => undefined);
  }, []);

  const refreshClock = useCallback(() => {
    getDeviceClock()
      .then(setClock)
      .catch(() => undefined);
  }, []);

  const refreshAll = useCallback(() => {
    refreshDoses();
    refreshClock();
    getElderlyDetail()
      .then(setElderly)
      .catch(() => undefined);
    getNotificationPreferences()
      .then(setPrefs)
      .catch(() => undefined);
  }, [refreshDoses, refreshClock]);

  useEffect(() => {
    if (enabled) refreshAll();
  }, [enabled, refreshAll]);

  /** Optimistic toggle; returns false (and restores the old value) when saving failed. */
  const togglePreference = async (key: PreferenceToggle, value: boolean): Promise<boolean> => {
    if (!prefs) return false;
    const before = prefs;
    const next = { ...prefs, [key]: value };
    setPrefs(next);
    setPrefsBusy(key);
    try {
      setPrefs(await saveNotificationPreferences(next));
      return true;
    } catch {
      setPrefs(before);
      return false;
    } finally {
      setPrefsBusy(null);
    }
  };

  const setAutoSync = async (value: boolean): Promise<boolean> => {
    if (!clock) return false;
    const before = clock;
    setClock({ ...clock, autoSyncTimezone: value });
    try {
      await setAutoSyncTimezone(value);
      return true;
    } catch {
      setClock(before);
      return false;
    }
  };

  const calibrate = async (pin: string) => {
    await calibrateDeviceClock(pin);
    refreshClock();
  };

  return {
    todayDoses,
    dosesError,
    week,
    elderly,
    clock,
    prefs,
    prefsBusy,
    refreshDoses,
    refreshAll,
    togglePreference,
    setAutoSync,
    calibrate,
  };
}

export type DashboardInsights = ReturnType<typeof useDashboardInsights>;
