import { useEffect, useRef } from 'react';
import { AppState } from 'react-native';

export type PollingOptions = {
  /** Stop while the app is in the background (or the browser tab is hidden). Default true. */
  pauseInBackground?: boolean;
  /** Run once right away instead of after the first interval. Default false. */
  immediate?: boolean;
  /** Run once when the app comes back to the foreground. Default true. */
  runOnResume?: boolean;
  /**
   * While this returns true (e.g. the push socket is live) the poll is only a safety net and waits
   * `slowIntervalMs` instead. Both must be set to take effect.
   */
  slowWhen?: () => boolean;
  slowIntervalMs?: number;
};

/**
 * Runs `task` every `intervalMs` (null = stopped) as a setTimeout chain, so a slow run never
 * overlaps the next one. Pauses in the background to save battery and data; on resume it runs
 * once at once, because whatever it shows may be stale.
 */
export function usePolling(task: () => unknown, intervalMs: number | null, options: PollingOptions = {}): void {
  const { pauseInBackground = true, immediate = false, runOnResume = true, slowWhen, slowIntervalMs } = options;
  // The latest task and slow check, read when the timer fires (callers pass inline closures).
  const taskRef = useRef(task);
  const slowRef = useRef(slowWhen);
  useEffect(() => {
    taskRef.current = task;
    slowRef.current = slowWhen;
  }, [task, slowWhen]);

  useEffect(() => {
    if (intervalMs === null) return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;
    let running = false;

    const delay = () => (slowIntervalMs !== undefined && slowRef.current?.() ? slowIntervalMs : intervalMs);
    const schedule = () => {
      if (timer) clearTimeout(timer);
      timer = stopped ? null : setTimeout(() => void run(), delay());
    };
    const run = async () => {
      if (timer) clearTimeout(timer);
      timer = null;
      if (stopped || running) return;
      running = true;
      try {
        await taskRef.current();
      } catch {
        // the task reports its own errors; a failed run never stops the loop
      } finally {
        running = false;
        if (!stopped && (!pauseInBackground || AppState.currentState !== 'background')) schedule();
      }
    };

    if (immediate) void run();
    else schedule();

    const sub = AppState.addEventListener('change', (next) => {
      if (!pauseInBackground) return;
      if (next === 'active') {
        if (runOnResume) void run();
        else schedule();
      } else if (next === 'background' && timer) {
        clearTimeout(timer);
        timer = null;
      }
    });
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      sub.remove();
    };
  }, [intervalMs, pauseInBackground, immediate, runOnResume, slowIntervalMs]);
}
