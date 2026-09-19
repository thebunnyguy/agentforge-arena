// In-app link builders. Run links use the exact run id when the server gave
// one: (agent, task, idx) collides across task versions. Rows without a run id
// (synthetic reference baselines) keep the tuple route.

export function runHref(
  run: { run_id?: number | null; idx: number },
  agent: string,
  taskId: string,
): string {
  if (typeof run.run_id === "number") return `/runs/${run.run_id}`;
  return `/cell/${encodeURIComponent(agent)}/${encodeURIComponent(taskId)}/run/${run.idx}`;
}
