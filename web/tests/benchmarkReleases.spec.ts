// Pure logic: the generated release datasets are checked against the frozen
// campaign artifacts they were built from (never against themselves), and the
// registry helpers are checked on synthetic releases. No page, no server.
import { readFileSync, readdirSync } from "node:fs";
import { expect, test } from "@playwright/test";
import {
  asBenchmarkRelease,
  caveatsFor,
  findModel,
  findRelease,
  isCampaignMethodology,
  modelPath,
  orderReleases,
  ReleaseDataError,
  selectDefaultRelease,
  type BenchmarkRelease,
} from "../src/lib/benchmarkReleases";
import {
  cellSummaryText,
  formatReleaseDate,
  formatUtcTimestamp,
  gigabytesText,
  intervalText,
  plainRankingText,
  rankText,
  releaseDateLabel,
  seedsText,
  timeoutsText,
} from "../src/lib/benchmarkDisplay";

const repo = new URL("../..", import.meta.url);
const readText = (path: string) => readFileSync(new URL(path, repo), "utf8");
const readJson = (path: string): any => JSON.parse(readText(path));

const CAMPAIGN = "campaigns/phase0-modern-local-v1";
const DATA = "web/src/data/benchmark-releases";

const official = asBenchmarkRelease(
  readJson(`${DATA}/phase0-modern-local-v1.json`),
);
const historical = asBenchmarkRelease(
  readJson(`${DATA}/historical-pre-phase0.json`),
);

const manifest = readJson(`${CAMPAIGN}/manifest.json`);
const leaderboard = readJson(
  `${CAMPAIGN}/results/outputs/modern-local-leaderboard.json`,
);
const completeness = readJson(
  `${CAMPAIGN}/results/outputs/completeness-receipt-all.json`,
);
const receiptDir = `${CAMPAIGN}/results/receipts/`;
const receipts = new Map<string, any>(
  readdirSync(new URL(receiptDir, repo))
    .filter((name) => name.endsWith(".json"))
    .map((name) => {
      const receipt = readJson(`${receiptDir}${name}`);
      return [receipt.model as string, receipt];
    }),
);
const promotion = readText("docs/release/PHASE0_MODERN_LOCAL_PROMOTION.md");

const normalize = (text: string) =>
  text.replace(/\s+/g, " ").trim().replace(/\.$/, "");
// The italic (single-asterisk) sentences of the promotion receipt are the
// required caveat wording.
const requiredSentences = [
  ...promotion.matchAll(/(?<!\*)\*(?!\*)([^*]+)(?<!\*)\*(?!\*)/g),
].map((m) => normalize(m[1]));

const COMPARABILITY =
  "Historical results are not directly comparable with Modern Local v1. Eighteen of the 24 task definitions changed and the historical runs predate the current evaluation-integrity system.";

test.describe("Modern Local v1 dataset matches the frozen campaign artifacts", () => {
  test("identity and counts", () => {
    expect(official.id).toBe(manifest.campaign_id);
    expect(official.campaign_id).toBe(manifest.campaign_id);
    expect(official.status).toBe("OFFICIAL");
    expect(official.ranked).toBe(true);
    expect(leaderboard.official).toBe(true);
    expect(official.models).toHaveLength(manifest.roster.length);
    expect(official.models).toHaveLength(5);
    expect(official.counts.models).toBe(5);
    expect(official.counts.runs).toBe(completeness.present.runs);
    expect(official.counts.runs).toBe(completeness.expected.runs);
    expect(official.counts.runs).toBe(600);
    expect(official.counts.evaluations).toBe(completeness.expected.cells);
    expect(official.counts.evaluations).toBe(120);
    expect(official.counts.tasks).toBe(manifest.tasks.length);
    expect(official.counts.tasks).toBe(24);
    expect(official.counts.repetitions).toBe(manifest.repetitions);
    for (const model of official.models) {
      expect(model.totals.runs).toBe(
        completeness.expected.runs_per_model[model.id],
      );
      expect(model.totals.runs).toBe(120);
    }
  });

  test("rank order, passes, pass rate and Wilson interval", () => {
    const rows = leaderboard.leaderboard as Array<{
      agent: string;
      rank_low: number;
      rank_high: number;
      provisional: boolean;
      pass_rate: number;
      wilson_low: number;
      wilson_high: number;
      n: number;
      timeouts: number;
      request_timeout_hits: number;
      agent_errors: number;
      coverage: { cells_with_fresh_evidence: number; manifest_tasks: number };
    }>;
    expect(official.models.map((m) => m.id)).toEqual(rows.map((r) => r.agent));
    rows.forEach((row, index) => {
      const model = official.models[index];
      expect(model.rank).toEqual({
        low: row.rank_low,
        high: row.rank_high,
        provisional: row.provisional,
      });
      expect(model.totals.pass_rate).toBe(row.pass_rate);
      expect(model.totals.wilson_low).toBe(row.wilson_low);
      expect(model.totals.wilson_high).toBe(row.wilson_high);
      expect(model.totals.runs).toBe(row.n);
      expect(model.totals.timeouts).toBe(row.timeouts);
      expect(model.totals.request_timeout_hits).toBe(row.request_timeout_hits);
      expect(model.totals.agent_errors).toBe(row.agent_errors);
      expect(model.coverage).toEqual({
        tasks_with_evidence: row.coverage.cells_with_fresh_evidence,
        tasks_total: row.coverage.manifest_tasks,
      });
      const receipt = receipts.get(model.id);
      expect(receipt, model.id).toBeTruthy();
      expect(model.totals.passes).toBe(receipt.totals.passed);
      expect(model.totals.passes).toBe(completeness.per_model[model.id].passed);
      expect(model.totals.mean_final_score).toBe(
        receipt.aggregate.mean_final_score,
      );
    });
    expect(official.models[0].totals.passes).toBe(96);
  });

  test("model identity equals the manifest roster pins", () => {
    for (const entry of manifest.roster) {
      const model = findModel(official, entry.model);
      expect(model, entry.model).toBeTruthy();
      expect(model!.display_name).toBe(entry.logical_name);
      expect(model!.identity.digest).toBe(entry.expected_identity.digest);
      expect(model!.identity.download_bytes).toBe(
        entry.expected_identity.download_bytes,
      );
      expect(model!.identity.quantization).toBe(
        entry.expected_identity.quantization,
      );
    }
  });

  test("task pack equals the manifest tasks", () => {
    expect(
      official.task_pack.map((t) => [t.task_id, t.task_version, t.task_digest]),
    ).toEqual(
      manifest.tasks.map((t: Record<string, string>) => [
        t.task_id,
        t.task_version,
        t.task_digest,
      ]),
    );
  });

  test("every model × task cell equals the receipts", () => {
    const cells = new Map<string, Record<string, number>>(
      completeness.cells.map((c: Record<string, number> & { cell: string }) => [
        c.cell,
        c,
      ]),
    );
    let checked = 0;
    for (const model of official.models) {
      const receiptCells = new Map<string, Record<string, number>>(
        receipts
          .get(model.id)
          .cells.map((c: Record<string, number> & { task_id: string }) => [
            c.task_id,
            c,
          ]),
      );
      for (const task of model.tasks) {
        const cell = cells.get(`${model.id}|${task.task_id}`);
        const receiptCell = receiptCells.get(task.task_id);
        expect(cell, `${model.id}|${task.task_id}`).toBeTruthy();
        expect(task.passes).toBe(cell!.passed);
        expect(task.passes).toBe(receiptCell!.passed);
        expect(task.runs).toBe(receiptCell!.valid);
        expect(task.runs).toBe(cell!.valid);
        expect(task.timeouts).toBe(receiptCell!.timeouts);
        expect(task.request_timeout_hits).toBe(
          receiptCell!.request_timeout_hits,
        );
        checked += 1;
      }
    }
    expect(checked).toBe(120);
  });

  test("integrity counts equal the completeness receipt", () => {
    const integrity = official.integrity!;
    const classes = completeness.evidence_classes as Record<string, number>;
    expect(integrity.complete).toBe(completeness.complete);
    expect(integrity.accepted_runs).toBe(completeness.present.runs);
    expect(integrity.planned_runs).toBe(completeness.expected.runs);
    expect(integrity.valid_runs).toBe(completeness.present.valid_runs);
    expect(integrity.models_complete).toBe(
      completeness.present.models_complete,
    );
    expect(integrity.models_total).toBe(completeness.expected.models);
    expect(integrity.missing_runs).toBe(completeness.missing.positions);
    expect(integrity.missing_evaluations).toBe(
      completeness.missing.cells.length,
    );
    expect(integrity.extra_runs).toBe(
      completeness.extra.campaign_owned_positions_beyond_plan,
    );
    expect(integrity.untracked_evaluations).toBe(
      completeness.extra.untracked_campaign_evaluations.length,
    );
    expect(integrity.disowned_evaluations).toBe(
      completeness.extra.disowned_evaluations.length,
    );
    expect(integrity.voided_runs).toBe(completeness.voided_positions);
    for (const cls of ["real", "synthetic", "legacy", "conflict"] as const) {
      expect(integrity.evidence_classes[cls], cls).toBe(classes[cls] ?? 0);
    }
    expect(integrity.problems).toEqual(completeness.problems);
    expect(
      integrity.not_claimed.map((n) => [n.property, n.status]),
    ).toContainEqual(["Hidden-test isolation", "UNVERIFIABLE"]);
  });

  test("model caveats carry the required wording", () => {
    const protocol = official.caveats.find(
      (c) => c.kind === "protocol-sensitivity",
    )!;
    expect(protocol.model).toBe("qwen3-coder:30b");
    expect(requiredSentences).toContain(normalize(protocol.summary));
    expect(findModel(official, "qwen3-coder:30b")!.caveat_ids).toEqual([
      protocol.id,
    ]);

    const latency = official.caveats.find(
      (c) => c.kind === "latency-constrained",
    )!;
    expect(latency.model).toBe("qwen3.6:27b");
    expect(requiredSentences).toContain(normalize(latency.summary));
    const m5 = receipts.get("qwen3.6:27b").totals;
    expect(m5.timeouts).toBe(105);
    expect(m5.request_timeout_hits).toBe(83);
    expect(latency.points.join(" ")).toContain(
      `${m5.timeouts} of ${m5.valid} runs`,
    );
    expect(latency.points.join(" ")).toContain(`${m5.request_timeout_hits} of`);
    expect(findModel(official, "qwen3.6:27b")!.caveat_ids).toEqual([
      latency.id,
    ]);

    const others = official.models.filter(
      (m) => m.id !== "qwen3-coder:30b" && m.id !== "qwen3.6:27b",
    );
    for (const model of others) expect(model.caveat_ids, model.id).toEqual([]);
    expect(caveatsFor(official, null).map((c) => c.kind)).toEqual([
      "non-comparable",
    ]);
  });

  test("methodology is the campaign's frozen generation settings", () => {
    const methodology = official.methodology;
    expect(isCampaignMethodology(methodology)).toBe(true);
    if (!isCampaignMethodology(methodology)) return;
    expect(methodology.temperature).toBe(manifest.generation.temperature);
    expect(methodology.request_timeout_s).toBe(
      manifest.generation.request_timeout_s,
    );
    expect(methodology.ollama_version).toBe(
      manifest.execution.ollama_server_version,
    );
    expect(methodology.runtime_release.tag).toBe(
      manifest.code.runtime_release_tag,
    );
    expect(methodology.manifest_sha256).toBe(leaderboard.manifest_sha256);
  });
});

test.describe("historical pre-Phase-0 dataset", () => {
  test("is HISTORICAL, unranked and not comparable", () => {
    expect(historical.status).toBe("HISTORICAL");
    expect(historical.ranked).toBe(false);
    expect(historical.comparable).toBe(false);
    expect(historical.comparability).toBe(COMPARABILITY);
    expect(historical.counts.runs).toBe(720);
    expect(historical.counts.models).toBe(6);
    expect(historical.models).toHaveLength(6);
    expect(historical.integrity).toBeNull();
    expect(historical.environment).toBeNull();
    expect(historical.models.every((m) => m.rank === null)).toBe(true);
    expect(isCampaignMethodology(historical.methodology)).toBe(false);
  });

  test("lists its models alphabetically by Ollama tag, not by result", () => {
    const tags = historical.models.map((m) => m.identity.ollama_tag);
    expect(tags).toEqual([...tags].sort());
    expect(historical.models[0].id).toBe("deepseek-coder:6.7b");
    expect(historical.models[0].totals.passes).toBe(28);
    const passes = historical.models.map((m) => m.totals.passes);
    expect(passes).not.toEqual([...passes].sort((a, b) => b - a));
  });

  test("generation groups carry no free-text note", () => {
    if (isCampaignMethodology(historical.methodology)) throw new Error();
    for (const group of historical.methodology.generation_groups)
      expect(Object.keys(group)).not.toContain("note");
  });

  test("carries no intervals, pass rates or synthetic baselines", () => {
    const keys = new Set<string>();
    const walk = (value: unknown) => {
      if (Array.isArray(value)) value.forEach(walk);
      else if (value && typeof value === "object")
        for (const [key, child] of Object.entries(value)) {
          keys.add(key);
          walk(child);
        }
    };
    walk(historical);
    for (const key of keys) {
      expect(key.toLowerCase()).not.toContain("wilson");
      expect(key).not.toBe("pass_rate");
    }
    for (const model of historical.models) {
      expect(model.id).not.toMatch(/oracle|noop/i);
    }
  });
});

// A release that differs from the official one only in its metadata. The
// validator's cross-checks (task coverage, run totals) still hold.
function variant(
  base: BenchmarkRelease,
  changes: Partial<BenchmarkRelease>,
): BenchmarkRelease {
  return asBenchmarkRelease({ ...structuredClone(base), ...changes });
}

test.describe("registry semantics", () => {
  test("the default is the OFFICIAL release", () => {
    expect(selectDefaultRelease([historical, official]).id).toBe(official.id);
    expect(findRelease([historical, official], undefined)!.id).toBe(
      official.id,
    );
    expect(findRelease([historical, official], "nope")).toBeUndefined();
  });

  test("a newer EXPERIMENTAL release does not become the default", () => {
    const experimental = variant(official, {
      id: "experimental-next",
      status: "EXPERIMENTAL",
      released_at: "2027-01-01",
    });
    expect(selectDefaultRelease([experimental, historical, official]).id).toBe(
      official.id,
    );
  });

  test("a newer OFFICIAL release becomes the default", () => {
    const newer = variant(official, {
      id: "official-next",
      released_at: "2027-01-01",
    });
    expect(selectDefaultRelease([official, historical, newer]).id).toBe(
      "official-next",
    );
  });

  test("with no OFFICIAL release, the newest non-historical wins", () => {
    const superseded = variant(official, {
      id: "old",
      status: "SUPERSEDED",
      released_at: "2026-01-01",
    });
    const experimental = variant(official, {
      id: "exp",
      status: "EXPERIMENTAL",
      released_at: "2026-10-01",
    });
    const newestHistorical = variant(historical, { released_at: "2030-01-01" });
    expect(
      selectDefaultRelease([superseded, newestHistorical, experimental]).id,
    ).toBe("exp");
  });

  test("orderReleases puts HISTORICAL last", () => {
    const experimental = variant(official, {
      id: "exp",
      status: "EXPERIMENTAL",
      released_at: "2026-10-01",
    });
    const order = orderReleases([historical, experimental, official]);
    expect(order.map((r) => r.id)).toEqual([official.id, "exp", historical.id]);
    expect(order[order.length - 1].status).toBe("HISTORICAL");
  });

  test("asBenchmarkRelease rejects an unknown status", () => {
    expect(() =>
      asBenchmarkRelease({ ...structuredClone(official), status: "BETA" }),
    ).toThrow(ReleaseDataError);
  });

  test("asBenchmarkRelease rejects a model that does not cover the task pack", () => {
    const broken = structuredClone(official);
    broken.models[0].tasks = broken.models[0].tasks.slice(1);
    expect(() => asBenchmarkRelease(broken)).toThrow(/does not cover/);
  });

  test("model links encode ':' and '.'", () => {
    expect(modelPath(official, "qwen3.6:27b")).toBe(
      "/benchmarks/phase0-modern-local-v1/models/qwen3.6%3A27b",
    );
  });
});

test("display helpers format served values without recomputing them", () => {
  expect(formatReleaseDate("2026-09-28")).toBe("Sep 28, 2026");
  expect(formatUtcTimestamp("2026-06-18 06:11:14")).toBe(
    "2026-06-18 06:11 UTC",
  );
  expect(formatUtcTimestamp("2026-09-27T23:09:55Z")).toBe(
    "2026-09-27 23:09 UTC",
  );
  const gpt = official.models[0].totals;
  expect(intervalText(gpt.wilson_low!, gpt.wilson_high!)).toBe("72.0–86.2%");
  expect(timeoutsText(105, 83)).toBe("105 (83 full)");
  expect(timeoutsText(36)).toBe("36");
  expect(
    gigabytesText(
      findModel(official, "qwen3-coder:30b")!.identity.download_bytes,
    ),
  ).toBe("18.56 GB");
  if (isCampaignMethodology(official.methodology))
    expect(seedsText(official.methodology.seeds)).toBe("42–46");
});

test.describe("rank text comes from the served rank, never the position", () => {
  // A synthetic release whose list order disagrees with rank.low: a display
  // that printed index + 1 would give 1, 2, 3 here.
  const models = structuredClone(official.models).slice(0, 3);
  models[0].rank = { low: 2, high: 3, provisional: false };
  models[1].rank = { low: 7, high: 7, provisional: false };
  models[2].rank = { low: 1, high: 1, provisional: true };

  test("rankText prints rank.low (or its tie band) as served", () => {
    expect(models.map(rankText)).toEqual(["2–3", "7", "provisional"]);
    expect(rankText({ rank: null })).toBe("—");
    expect(official.models.map((m) => rankText(m))).toEqual(
      official.models.map((m) => String(m.rank!.low)),
    );
  });
});

test("display text helpers: date label, ranking text, cell summary", () => {
  expect(releaseDateLabel("HISTORICAL")).toBe("Last recorded run");
  expect(releaseDateLabel("OFFICIAL")).toBe("Released");
  if (!isCampaignMethodology(official.methodology)) throw new Error();
  const plain = plainRankingText(official.methodology.ranking_method);
  expect(plain).not.toMatch(/\.py|\(|\)/);
  expect(plain).toContain("Wilson 95% lower bound");
  expect(plain).toContain("Pass rate alone does not order the table.");
  expect(plainRankingText("A (x/y.py) b, c (d).")).toBe("A b, c.");

  const qwen36 = findModel(official, "qwen3.6:27b")!;
  const cell = qwen36.tasks.find((t) => t.task_id === "escape-html")!;
  expect(cellSummaryText("escape-html 1.0.1", qwen36.display_name, cell)).toBe(
    `escape-html 1.0.1 · Qwen3.6 27B: ${cell.passes} of ${cell.runs} passed, Wilson ${intervalText(cell.wilson_low!, cell.wilson_high!)}, ${cell.timeouts} timeouts (${cell.request_timeout_hits} full)`,
  );
  expect(
    cellSummaryText("t 1", "m", {
      task_id: "t",
      task_version: "1",
      evidence: false,
    }),
  ).toBe("t 1 · m: no evidence");
  const recorded = historical.models[0].tasks[0];
  expect(
    cellSummaryText("escape-html 1.0.1", "deepseek-coder:6.7b", recorded),
  ).toBe(
    `escape-html 1.0.1 · deepseek-coder:6.7b: ${recorded.passes} of ${recorded.runs} passed, ${recorded.timeouts} ${recorded.timeouts === 1 ? "timeout" : "timeouts"}`,
  );
});

test("every generated dataset is registered and every definition has a dataset", () => {
  const registry = readText(`${DATA}/index.ts`);
  const datasets = readdirSync(new URL(`${DATA}/`, repo)).filter((name) =>
    name.endsWith(".json"),
  );
  const definitions = readdirSync(new URL("campaigns/releases/", repo))
    .filter((name) => name.endsWith(".json"))
    .map((name) => name.replace(/\.json$/, ""));
  expect(datasets.map((name) => name.replace(/\.json$/, "")).sort()).toEqual(
    [...definitions].sort(),
  );
  for (const name of datasets) {
    expect(registry, `${name} is imported by the registry`).toContain(
      `from "./${name}"`,
    );
  }
});
