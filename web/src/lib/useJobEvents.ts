import { useEffect, useRef, useState } from "react";
import { api, jobEventsSseUrl } from "../api/client";
import { drainJobEvents } from "./jobEvents";
import type { JobEvent } from "../api/types";

export type Transport = "sse" | "poll" | "closed";

export interface JobEventStream {
  events: JobEvent[];
  lastSeq: number;
  transport: Transport;
  connected: boolean;
  historyLoading: boolean;
  historyError: Error | null;
}

const TERMINAL_EVENTS = new Set(["job_done", "job_failed", "job_canceled"]);
const EVENT_TYPES = [
  "job_started",
  "job_reclaimed",
  "run_started",
  "run_diff",
  "run_diffed",
  "run_graded",
  "run_scored",
  "run_persisted",
  "run_skipped",
  "progress",
  "log",
  "error",
  "job_done",
  "job_failed",
  "job_canceled",
  "close",
];

// The first read is JSON so historical timestamps and pagination are preserved.
// SSE is then used for tailing; both paths share the same sequence deduplication.
export function useJobEvents(jobId: string, active: boolean): JobEventStream {
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [transport, setTransport] = useState<Transport>(
    active ? "sse" : "closed",
  );
  const [connected, setConnected] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(active);
  const [historyError, setHistoryError] = useState<Error | null>(null);
  const lastSeqRef = useRef(0);
  const seenRef = useRef<Set<number>>(new Set());

  useEffect(() => {
    setEvents([]);
    setTransport(active ? "sse" : "closed");
    setConnected(false);
    setHistoryLoading(active);
    setHistoryError(null);
    lastSeqRef.current = 0;
    seenRef.current = new Set();
  }, [active, jobId]);

  useEffect(() => {
    if (!active || !jobId) return;

    const abortController = new AbortController();
    let stopped = false;
    let eventSource: EventSource | null = null;
    let pollTimer: number | null = null;
    let sseFailures = 0;
    let terminalSeen = false;
    let closeSeen = false;

    const stop = (nextTransport: Transport = "closed") => {
      if (pollTimer !== null) window.clearTimeout(pollTimer);
      eventSource?.close();
      eventSource = null;
      if (!stopped) setTransport(nextTransport);
    };

    const ingest = (incoming: JobEvent[]): { useful: boolean } => {
      if (stopped) return { useful: false };
      const fresh: JobEvent[] = [];
      for (const event of incoming) {
        if (event.type === "close") {
          closeSeen = true;
          continue;
        }
        if (event.seq <= 0 || seenRef.current.has(event.seq)) continue;
        seenRef.current.add(event.seq);
        lastSeqRef.current = Math.max(lastSeqRef.current, event.seq);
        fresh.push(event);
        if (TERMINAL_EVENTS.has(event.type)) terminalSeen = true;
      }
      if (fresh.length > 0 && !stopped) {
        sseFailures = 0;
        setEvents((previous) =>
          [...previous, ...fresh].sort((a, b) => a.seq - b.seq),
        );
      }
      return { useful: fresh.length > 0 };
    };

    const reader = {
      events: async (id: string, since: number) =>
        (await api.jobEvents(id, since, abortController.signal)).events,
      job: (id: string) => api.job(id, abortController.signal),
    };

    const pollPages = async (): Promise<{
      progressed: boolean;
      terminal: boolean;
    }> => {
      const drained = await drainJobEvents(
        jobId,
        lastSeqRef.current,
        reader,
        1000,
        abortController.signal,
      );
      if (stopped) return { progressed: false, terminal: false };
      const received = ingest(drained.events);
      if (drained.terminal && !received.useful) terminalSeen = true;
      return { progressed: received.useful, terminal: drained.terminal };
    };

    const poll = () => {
      setTransport("poll");
      const tick = async () => {
        if (stopped) return;
        try {
          const result = await pollPages();
          if (stopped) return;
          setConnected(true);
          setHistoryLoading(false);
          setHistoryError(null);
          if (closeSeen || (result.terminal && !result.progressed)) {
            stop("closed");
            return;
          }
        } catch (caught) {
          if (stopped || abortController.signal.aborted) return;
          const error =
            caught instanceof Error ? caught : new Error(String(caught));
          setConnected(false);
          setHistoryLoading(false);
          setHistoryError(error);
        }
        if (!stopped) pollTimer = window.setTimeout(tick, 1500);
      };
      void tick();
    };

    const handleNamedEvent = (raw: Event) => {
      if (stopped) return;
      if (!(raw instanceof MessageEvent) || typeof raw.data !== "string")
        return;
      const message = raw as MessageEvent<string>;
      if (message.type === "close") {
        closeSeen = true;
        stop("closed");
        return;
      }
      let payload: Record<string, unknown> | null = null;
      try {
        const parsed: unknown = JSON.parse(message.data);
        payload =
          parsed && typeof parsed === "object"
            ? (parsed as Record<string, unknown>)
            : { value: parsed };
      } catch {
        payload = { raw: message.data };
      }
      ingest([
        {
          job_id: jobId,
          seq: Number(message.lastEventId || 0),
          ts: null,
          type: message.type,
          payload,
        },
      ]);
      if (!stopped) setHistoryLoading(false);
      if (TERMINAL_EVENTS.has(message.type)) {
        terminalSeen = true;
        stop("closed");
      }
    };

    const connectSse = () => {
      try {
        eventSource = new EventSource(jobEventsSseUrl(jobId));
      } catch (caught) {
        if (!stopped)
          setHistoryError(
            caught instanceof Error ? caught : new Error(String(caught)),
          );
        poll();
        return;
      }
      eventSource.onopen = () => {
        if (stopped) return;
        setConnected(true);
        setTransport("sse");
        setHistoryLoading(false);
        // Opening a socket without data does not reset the bounded failure count.
      };
      eventSource.onmessage = handleNamedEvent;
      for (const eventType of EVENT_TYPES)
        eventSource.addEventListener(eventType, handleNamedEvent);
      eventSource.onerror = (raw) => {
        if (stopped) return;
        // Browsers may route a named worker error through onerror too. Only a
        // MessageEvent carrying data is a worker event, not a transport error.
        if (raw instanceof MessageEvent && typeof raw.data === "string") {
          handleNamedEvent(raw);
          return;
        }
        setConnected(false);
        if (terminalSeen || closeSeen) return;
        sseFailures += 1;
        if (sseFailures >= 3) {
          eventSource?.close();
          eventSource = null;
          poll();
        }
      };
    };

    const loadInitialHistory = async () => {
      try {
        const initial = await drainJobEvents(
          jobId,
          0,
          reader,
          1000,
          abortController.signal,
        );
        if (stopped) return;
        ingest(initial.events);
        setHistoryLoading(false);
        setHistoryError(null);
        if (initial.terminal) {
          terminalSeen = true;
          stop("closed");
          return;
        }
        connectSse();
      } catch (caught) {
        if (stopped || abortController.signal.aborted) return;
        setHistoryLoading(false);
        setHistoryError(
          caught instanceof Error ? caught : new Error(String(caught)),
        );
        poll();
      }
    };

    void loadInitialHistory();
    return () => {
      stopped = true;
      abortController.abort();
      if (pollTimer !== null) window.clearTimeout(pollTimer);
      eventSource?.close();
      eventSource = null;
    };
  }, [active, jobId]);

  return {
    events,
    lastSeq: lastSeqRef.current,
    transport,
    connected,
    historyLoading,
    historyError,
  };
}
