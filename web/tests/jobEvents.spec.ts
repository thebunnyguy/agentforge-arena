import { expect, test } from "@playwright/test";
import type { JobEvent } from "../src/api/types";
import { drainJobEvents } from "../src/lib/jobEvents";

function makeEvent(seq: number): JobEvent {
  return {
    job_id: "job",
    seq,
    ts: "2026-09-09 20:00:00",
    type: "log",
    payload: { seq },
  };
}

test("drains more than one 1000-event page and deduplicates replay", async () => {
  const all = Array.from({ length: 1001 }, (_, index) => makeEvent(index + 1));
  const cursors: number[] = [];
  const result = await drainJobEvents("job", 0, {
    events: async (_jobId, since) => {
      cursors.push(since);
      return since === 0 ? all.slice(0, 1000) : [all[999], all[1000]];
    },
    job: async () => ({ status: "succeeded" }),
  });

  expect(result.events).toHaveLength(1001);
  expect(result.events[0].seq).toBe(1);
  expect(result.events.at(-1)?.seq).toBe(1001);
  expect(result.lastSeq).toBe(1001);
  expect(result.terminal).toBe(true);
  expect(cursors).toEqual([0, 1000]);
});

test("reads lifecycle state before draining a final terminal event suffix", async () => {
  let stateRead = false;
  const result = await drainJobEvents("job", 0, {
    events: async () => (stateRead ? [makeEvent(1)] : []),
    job: async () => {
      stateRead = true;
      return { status: "succeeded" };
    },
  });

  expect(result.events.map((event) => event.seq)).toEqual([1]);
  expect(result.status).toBe("succeeded");
  expect(result.terminal).toBe(true);
});

test("closes a queued-canceled job even when it has no terminal event", async () => {
  const result = await drainJobEvents("job", 0, {
    events: async () => [],
    job: async () => ({ status: "canceled" }),
  });

  expect(result.events).toEqual([]);
  expect(result.terminal).toBe(true);
  expect(result.status).toBe("canceled");
});
