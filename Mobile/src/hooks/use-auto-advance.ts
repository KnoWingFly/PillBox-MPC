import { useEffect, useState } from 'react';

/**
 * Index that moves to the next item every `intervalMs` and wraps around. Picking an index by hand
 * restarts the wait, and nothing moves while `paused` (e.g. the pointer is over the content).
 */
export function useAutoAdvance(count: number, intervalMs: number, paused = false) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (paused || count <= 1) return;
    const timer = setTimeout(() => setIndex((i) => (i + 1) % count), intervalMs);
    return () => clearTimeout(timer);
  }, [index, count, intervalMs, paused]);

  return [index, setIndex] as const;
}
