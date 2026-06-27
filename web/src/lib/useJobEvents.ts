import { useEffect, useRef, useState } from "react";
import { api, jobEventsSseUrl } from "../api/client";
import type { JobEvent } from "../api/types";

export type Transport = "sse" | "poll" | "closed";

export interface JobEventStream {
  events: JobEvent[];
  lastSeq: number;
  transport: Transport;
  connected: boolean;
}

const TERMINAL = new Set(["job_done", "job_failed", "job_canceled"]);

// Live job event stream.
//
// Primary transport: EventSource SSE. The browser natively resumes with
// Last-Event-ID, but to be safe across server restarts we ALSO track the last
// seq we've applied and dedupe by seq, so a replay-from-start never produces
// duplicate rows. If SSE errors repeatedly (or isn't usable), we fall back to
// polling GET /events?since=<lastSeq>.
export function useJobEvents(jobId: string, active: boolean): JobEventStream {
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [transport, setTransport] = useState<Transport>("sse");
  const [connected, setConnected] = useState(false);
  const lastSeqRef = useRef(0);
  const seenRef = useRef<Set<number>>(new Set());

  // Reset when the job changes.
  useEffect(() => {
    setEvents([]);
    setTransport("sse");
    setConnected(false);
    lastSeqRef.current = 0;
    seenRef.current = new Set();
  }, [jobId]);

  function ingest(incoming: JobEvent[]) {
    if (incoming.length === 0) return;
    const fresh: JobEvent[] = [];
    for (const ev of incoming) {
      if (seenRef.current.has(ev.seq)) continue;
      seenRef.current.add(ev.seq);
      if (ev.seq > lastSeqRef.current) lastSeqRef.current = ev.seq;
      fresh.push(ev);
    }
    if (fresh.length === 0) return;
    setEvents((prev) => [...prev, ...fresh].sort((a, b) => a.seq - b.seq));
  }

  useEffect(() => {
    if (!active || !jobId) {
      setTransport("closed");
      return;
    }

    let es: EventSource | null = null;
    let pollTimer: number | null = null;
    let stopped = false;
    let sseFailures = 0;

    function startPolling() {
      setTransport("poll");
      const tick = async () => {
        if (stopped) return;
        try {
          const res = await api.jobEvents(jobId, lastSeqRef.current);
          setConnected(true);
          ingest(res.events);
          const terminal = res.events.some((e) => TERMINAL.has(e.type));
          if (terminal) {
            setTransport("closed");
            return; // stop polling on terminal
          }
        } catch {
          setConnected(false);
        }
        if (!stopped) pollTimer = window.setTimeout(tick, 1500);
      };
      tick();
    }

    function startSse() {
      // Native EventSource manages reconnect + Last-Event-ID. We attach a
      // generic message listener plus named-event listeners so any event type
      // is captured. The seq comes from the SSE `id:` field (event.lastEventId).
      try {
        es = new EventSource(jobEventsSseUrl(jobId));
      } catch {
        startPolling();
        return;
      }

      const handle = (e: MessageEvent) => {
        sseFailures = 0;
        setConnected(true);
        const seq = Number(e.lastEventId || 0);
        let payload: Record<string, unknown> | null = null;
        let type = (e as MessageEvent).type;
        try {
          const parsed = JSON.parse(e.data);
          payload = parsed;
          if (parsed && typeof parsed === "object" && typeof parsed.type === "string") {
            type = parsed.type;
          }
        } catch {
          payload = { raw: e.data };
        }
        ingest([{ seq, ts: new Date().toISOString(), type, payload }]);
        if (TERMINAL.has(type)) {
          es?.close();
          setTransport("closed");
        }
      };

      es.onmessage = handle;
      for (const t of [
        "job_started",
        "run_started",
        "run_persisted",
        "progress",
        "job_done",
        "job_failed",
        "job_canceled",
        "log",
        "error",
      ]) {
        es.addEventListener(t, handle as EventListener);
      }

      es.onerror = () => {
        setConnected(false);
        sseFailures += 1;
        // EventSource auto-reconnects; if it keeps failing, fall back to poll.
        if (sseFailures >= 3) {
          es?.close();
          es = null;
          if (!stopped) startPolling();
        }
      };
    }

    if (typeof EventSource !== "undefined") {
      startSse();
    } else {
      startPolling();
    }

    return () => {
      stopped = true;
      es?.close();
      if (pollTimer) window.clearTimeout(pollTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, active]);

  return { events, lastSeq: lastSeqRef.current, transport, connected };
}
