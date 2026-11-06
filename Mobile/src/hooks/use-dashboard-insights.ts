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
import { scheduleTimezone } from '@root/lib/schedule-time';

type Loader = 'doses' | 'week' | 'elderly' | 'clock' | 'prefs';

/**
 * Data the redesigned tabs show besides status and schedules: today's doses, the weekly missed
 * chart, the elderly profile, the pillbox clock and notification preferences. The dashboard is
 * remounted per pillbox, so this hook belongs to one pillbox. `dayMs` is "now" on the pillbox clock.
 *
 * Every load has a generation number: an answer that arrives after a newer request for the same
 * data started (or after unmount) is dropped, so a slow old response never overwrites a newer one.
 */
export function useDashboardInsights(dayMs: number, enabled: boolean) {
  const [todayDoses, setTodayDoses] = useState<TodayDose[] | null>(null);
  const [dosesError, setDosesError] = useState(false);
  const [week, setWeek] = useState<WeekMissed | null>(null);
  const [weekError, setWeekError] = useState(false);
  const [elderly, setElderly] = useState<ElderlyDetail | null>(null);
  const [clock, setClock] = useState<DeviceClock | null>(null);
  const [prefs, setPrefs] = useState<NotificationPreferences | null>(null);
  const [prefsError, setPrefsError] = useState(false);
  const [prefsBusy, setPrefsBusy] = useState<PreferenceToggle | null>(null);
  // Read inside callbacks without re-creating them each tick of the pillbox clock.
  const dayRef = useRef(dayMs);
  useEffect(() => {
    dayRef.current = dayMs;
  }, [dayMs]);

  const generations = useRef<Record<Loader, number>>({ doses: 0, week: 0, elderly: 0, clock: 0, prefs: 0 });
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  /** Runs `load`; `apply` only if this is still the newest request of its kind. */
  const track = useCallback(<T,>(kind: Loader, load: () => Promise<T>, apply: (value: T) => void, fail: () => void) => {
    const generation = ++generations.current[kind];
    const current = () => mounted.current && generation === generations.current[kind];
    load().then(
      (value) => {
        if (current()) apply(value);
      },
      () => {
        if (current()) fail();
      },
    );
  }, []);

  // Timezone the shown doses were computed in; the clock load may learn a different one.
  const dosesTz = useRef<string | null>(null);

  const refreshDoses = useCallback(() => {
    dosesTz.current = scheduleTimezone();
    track(
      'doses',
      () => getTodayDoses(dayRef.current),
      (doses) => {
        setTodayDoses(doses);
        setDosesError(false);
      },
      () => setDosesError(true),
    );
    track(
      'week',
      () => getWeekMissed(dayRef.current),
      (value) => {
        setWeek(value);
        setWeekError(false);
      },
      () => setWeekError(true),
    );
  }, [track]);

  const refreshClock = useCallback(() => {
    track(
      'clock',
      getDeviceClock,
      (value) => {
        setClock(value);
        // The pillbox is not in the timezone the doses were computed in: compute them again.
        if (dosesTz.current !== null && dosesTz.current !== scheduleTimezone()) refreshDoses();
      },
      () => undefined,
    );
  }, [track, refreshDoses]);

  const refreshPrefs = useCallback(() => {
    track(
      'prefs',
      getNotificationPreferences,
      (value) => {
        setPrefs(value);
        setPrefsError(false);
      },
      () => setPrefsError(true),
    );
  }, [track]);

  const refreshAll = useCallback(() => {
    refreshDoses();
    refreshClock();
    track('elderly', getElderlyDetail, setElderly, () => undefined);
    refreshPrefs();
  }, [refreshDoses, refreshClock, refreshPrefs, track]);

  useEffect(() => {
    if (enabled) refreshAll();
  }, [enabled, refreshAll]);

  /** Optimistic toggle; returns false (and restores the old value) when saving failed. */
  const togglePreference = async (key: PreferenceToggle, value: boolean): Promise<boolean> => {
    if (!prefs || prefsBusy) return false;
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
    weekError,
    elderly,
    clock,
    prefs,
    prefsError,
    prefsBusy,
    refreshDoses,
    refreshPrefs,
    refreshAll,
    togglePreference,
    setAutoSync,
    calibrate,
  };
}

export type DashboardInsights = ReturnType<typeof useDashboardInsights>;
