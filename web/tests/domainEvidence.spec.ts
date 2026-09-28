import { expect, test } from "@playwright/test";
import type { DomainScore } from "../src/api/types";
import {
  domainEvidenceState,
  provisionalReason,
} from "../src/lib/domainEvidence";

const domain = (overrides: Partial<DomainScore>): DomainScore => ({
  domain: "security",
  pooled_pass_rate: 1,
  n_eff: 5,
  wilson_low: 0.566,
  wilson_high: 1,
  stability: 1,
  n_tasks: 1,
  n_runs: 5,
  displayable: false,
  ...overrides,
});

test("the server's displayable flag is the only authority on the threshold", () => {
  expect(
    domainEvidenceState(domain({ n_tasks: 5, n_runs: 25, displayable: true })),
  ).toBe("displayable");
  // Counts that would meet the threshold never promote a domain the server
  // did not mark displayable.
  expect(
    domainEvidenceState(domain({ n_tasks: 6, n_runs: 30, displayable: false })),
  ).toBe("provisional");
});

test("below-threshold domains with current evidence are provisional", () => {
  expect(domainEvidenceState(domain({}))).toBe("provisional");
  expect(domainEvidenceState(domain({ n_tasks: 2, n_runs: 10 }))).toBe(
    "provisional",
  );
  // A provisional 0% is real evidence (5 valid runs, none passed).
  expect(
    domainEvidenceState(
      domain({ pooled_pass_rate: 0, wilson_low: 0, wilson_high: 0.434 }),
    ),
  ).toBe("provisional");
});

test("a domain with no valid runs is 'none', not a 0% score", () => {
  // The kernel's degenerate placeholder for zero run mass.
  expect(
    domainEvidenceState(
      domain({
        pooled_pass_rate: 0,
        n_eff: 0,
        wilson_low: 0,
        wilson_high: 1,
        stability: 0,
        n_tasks: 0,
        n_runs: 0,
      }),
    ),
  ).toBe("none");
});

test("the provisional reason states the kernel's counts and the threshold", () => {
  expect(provisionalReason(domain({}))).toBe(
    "1 current task and 5 runs; the display threshold is 5 tasks and 25 runs",
  );
  expect(provisionalReason(domain({ n_tasks: 2, n_runs: 10 }))).toBe(
    "2 current tasks and 10 runs; the display threshold is 5 tasks and 25 runs",
  );
});
