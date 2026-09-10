import { useCallback, useEffect, useRef, useState } from "react";
import { ApiRequestError } from "../api/client";

export interface PollingState<T> {
  data: T | null;
  loading: boolean;
  error: ApiRequestError | Error | null;
  reload: () => void;
}

// Polling retains the last successful value while refreshing, so history pages
// never flash an empty/loading state during a background update.
export function usePolling<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  deps: ReadonlyArray<unknown>,
  intervalMs = 5000,
): PollingState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiRequestError | Error | null>(null);
  const [nonce, setNonce] = useState(0);
  const fnRef = useRef(fn);
  const requestRef = useRef<AbortController | null>(null);
  const activeRef = useRef(true);
  const hasDataRef = useRef(false);
  fnRef.current = fn;

  const reload = useCallback(() => setNonce((current) => current + 1), []);

  useEffect(() => {
    activeRef.current = true;
    let inFlight = false;
    const run = async (initial: boolean) => {
      if (!activeRef.current || inFlight) return;
      inFlight = true;
      requestRef.current?.abort();
      const controller = new AbortController();
      requestRef.current = controller;
      if (initial || !hasDataRef.current) setLoading(true);
      try {
        const next = await fnRef.current(controller.signal);
        if (!activeRef.current || controller.signal.aborted) return;
        setData(next);
        hasDataRef.current = true;
        setError(null);
        setLoading(false);
      } catch (caught) {
        if (!activeRef.current || controller.signal.aborted) return;
        setError(caught instanceof Error ? caught : new Error(String(caught)));
        setLoading(false);
      } finally {
        inFlight = false;
      }
    };
    void run(true);
    const timer = window.setInterval(() => void run(false), intervalMs);
    return () => {
      activeRef.current = false;
      window.clearInterval(timer);
      requestRef.current?.abort();
    };
    // `data` is intentionally not a dependency: polling retains it without
    // restarting the effect on each successful response.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, intervalMs]);

  return { data, loading, error, reload };
}
