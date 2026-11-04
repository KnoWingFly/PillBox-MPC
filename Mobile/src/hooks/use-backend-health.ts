import { useCallback, useState } from 'react';

import { isServerUnreachable } from '@root/lib/api';

/**
 * Whether the backend answered the dashboard's last request. `track` wraps a request: success marks
 * the server reachable, a network failure, timeout or 5xx marks it unreachable (a 4xx such as 404
 * says the server is up). The promise result is passed through unchanged.
 */
export function useBackendHealth() {
  const [unreachable, setUnreachable] = useState(false);
  const track = useCallback(<T,>(request: Promise<T>): Promise<T> => {
    return request.then(
      (value) => {
        setUnreachable(false);
        return value;
      },
      (err: unknown) => {
        setUnreachable(isServerUnreachable(err));
        throw err;
      },
    );
  }, []);
  return { unreachable, track };
}
