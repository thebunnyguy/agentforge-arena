// The benchmark release registry. Each dataset is generated from committed
// evidence by `python3 -m afa_campaign release-data` (see
// docs/benchmarks/BENCHMARK_RELEASES_UI.md); adding a release means generating
// its dataset and adding it to this list. The page picks its default release
// from the releases' own metadata (selectDefaultRelease), not from this order.
import {
  asBenchmarkRelease,
  orderReleases,
  selectDefaultRelease,
  type BenchmarkRelease,
} from "../../lib/benchmarkReleases";
import historicalPrePhase0 from "./historical-pre-phase0.json";
import phase0ModernLocalV1 from "./phase0-modern-local-v1.json";

export const benchmarkReleases: readonly BenchmarkRelease[] = orderReleases(
  [phase0ModernLocalV1, historicalPrePhase0].map(asBenchmarkRelease),
);

export const defaultRelease: BenchmarkRelease =
  selectDefaultRelease(benchmarkReleases);
