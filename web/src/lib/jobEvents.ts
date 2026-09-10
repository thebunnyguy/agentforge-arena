import type { JobEvent } from "../api/types";

const TERMINAL_STATES = new Set(["succeeded", "failed", "canceled"]);

export interface EventPageReader {
  events: (
    jobId: string,
    since: number,
    signal?: AbortSignal,
  ) => Promise<JobEvent[]>;
  job: (jobId: string, signal?: AbortSignal) => Promise<{ status: string }>;
}

export interface DrainedEvents {
  events: JobEvent[];
  lastSeq: number;
  terminal: boolean;
  status: string;
}

// Poll fallback must drain the API's bounded pages before deciding whether a
// terminal job is complete. This pure seam makes the 1000-row boundary and
// queued-cancel behavior testable without substituting data at runtime.
export async function drainJobEvents(
  jobId: string,
  since: number,
  reader: EventPageReader,
  pageSize = 1000,
  signal?: AbortSignal,
): Promise<DrainedEvents> {
  const seen = new Set<number>();
  const events: JobEvent[] = [];
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
  const initialState = await reader.job(jobId, signal);
  let cursor = since;
  for (let page = 0; page < 10000; page += 1) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const batch = await reader.events(jobId, cursor, signal);
    if (batch.length === 0) break;
    const before = cursor;
    for (const event of batch) {
      if (event.seq <= since || seen.has(event.seq)) continue;
      seen.add(event.seq);
      cursor = Math.max(cursor, event.seq);
      events.push(event);
    }
    if (batch.length < pageSize || cursor === before) break;
  }
  events.sort((a, b) => a.seq - b.seq);
  return {
    events,
    lastSeq: cursor,
    terminal: TERMINAL_STATES.has(initialState.status),
    status: initialState.status,
  };
}
