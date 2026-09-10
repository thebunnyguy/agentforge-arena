import { expect, test } from "@playwright/test";
import type { BackendVerifyResponse } from "../src/api/types";
import {
  hasVerifiedModel,
  validEvaluationParams,
  verificationKey,
} from "../src/lib/evaluationValidation";

const verified: BackendVerifyResponse = {
  kind: "mock",
  ok: true,
  detail: "ok",
  models: ["mock"],
};

test("stale verification cannot authorize a changed backend request", () => {
  const oldKey = verificationKey("mock", "");
  const newKey = verificationKey("ollama", "http://localhost:11434");
  expect(hasVerifiedModel(verified, oldKey, newKey, "mock")).toBe(false);
  expect(hasVerifiedModel(verified, oldKey, oldKey, "mock")).toBe(true);
});

test("model selection must belong to the current verified response", () => {
  const key = verificationKey("mock", "");
  expect(hasVerifiedModel(verified, key, key, "other-model")).toBe(false);
  expect(hasVerifiedModel(verified, key, key, "mock")).toBe(true);
});

test("experiment parameters require finite integer counts and seed", () => {
  expect(
    validEvaluationParams({
      repeats: 1,
      baseSeed: 42,
      temperature: 0.8,
      timeout: 180,
    }),
  ).toBe(true);
  expect(
    validEvaluationParams({
      repeats: 1.5,
      baseSeed: 42,
      temperature: 0.8,
      timeout: 180,
    }),
  ).toBe(false);
  expect(
    validEvaluationParams({
      repeats: 1,
      baseSeed: Number.NaN,
      temperature: 0.8,
      timeout: 180,
    }),
  ).toBe(false);
  expect(
    validEvaluationParams({
      repeats: 1,
      baseSeed: 42,
      temperature: Number.POSITIVE_INFINITY,
      timeout: 180,
    }),
  ).toBe(false);
});
