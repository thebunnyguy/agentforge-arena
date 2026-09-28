# OFFICIAL modern local leaderboard - phase0-modern-local-v1

Only models whose full 24 tasks x 5 repetitions batch is accepted are ranked; every other roster model is listed below with its state and is never ranked beside complete models.

## Roster

| phase | model | logical model | state | accepted runs | note |
|---|---|---|---|---|---|
| M1 | qwen3.5:9b | Qwen 3.5 9B | COMPLETE | 120 |  |
| M2 | gpt-oss:20b | gpt-oss 20B | COMPLETE | 120 |  |
| M3 | devstral-small-2:24b | Devstral Small 2 24B | COMPLETE | 120 |  |
| M4 | qwen3-coder:30b | Qwen3-Coder 30B-A3B | COMPLETE | 120 |  |
| M5 | qwen3.6:27b | Qwen3.6 27B | COMPLETE | 120 | optional |

- Evidence scope: `real`, campaign-owned only: the active 'succeeded' ledger entry of each manifest cell whose evaluation passes every campaign check (cohort.check_cell_evaluation).
- Excludes: mock / synthetic runs, legacy (unattested) runs, old task versions, provenance conflicts, evaluations the campaign ledger does not own, superseded ledger entries, cells failing a campaign check, the pre-Phase-0 historical evidence.
- Evaluations used: 120; runs used (ownership verified): 600.

## Leaderboard (kernel Wilson 95% lower-bound ranking)

| rank | model | n | pass rate | Wilson 95% | coverage | voided | timeouts (full request) | agent errors | provisional |
|---|---|---|---|---|---|---|---|---|---|
| 1 | gpt-oss:20b | 120 | 0.800 | [0.720, 0.862] | 24/24 | 0 | 0 (0) | 0 | no |
| 2 | devstral-small-2:24b | 120 | 0.592 | [0.502, 0.675] | 24/24 | 0 | 5 (0) | 0 | no |
| 3 | qwen3.5:9b | 120 | 0.333 | [0.255, 0.422] | 24/24 | 0 | 30 (19) | 0 | no |
| 4 | qwen3-coder:30b | 120 | 0.150 | [0.097, 0.225] | 24/24 | 0 | 0 (0) | 0 | no |
| 5 | qwen3.6:27b | 120 | 0.092 | [0.052, 0.157] | 24/24 | 0 | 105 (83) | 0 | no |

## Task matrix (passes/valid, Wilson 95%)

| task (version) | qwen3.5:9b | gpt-oss:20b | devstral-small-2:24b | qwen3-coder:30b | qwen3.6:27b |
|---|---|---|---|---|---|
| escape-html (1.0.1) | 5/5 [0.57, 1.00] | 5/5 [0.57, 1.00] | 1/5 [0.04, 0.62] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] |
| fix-binary-search (1.0.0) | 4/5 [0.38, 0.96] | 4/5 [0.38, 0.96] | 5/5 [0.57, 1.00] | 0/5 [0.00, 0.43] | 4/5 [0.38, 0.96] |
| fix-list-dedup (1.0.2) | 4/5 [0.38, 0.96] | 5/5 [0.57, 1.00] | 4/5 [0.38, 0.96] | 0/5 [0.00, 0.43] | 3/5 [0.23, 0.88] |
| async-retry (1.0.2) | 0/5 [0.00, 0.43] | 5/5 [0.57, 1.00] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] |
| async-timeout (1.0.1) | 2/5 [0.12, 0.77] | 4/5 [0.38, 0.96] | 4/5 [0.38, 0.96] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] |
| fix-roman-numerals (1.0.0) | 4/5 [0.38, 0.96] | 5/5 [0.57, 1.00] | 5/5 [0.57, 1.00] | 0/5 [0.00, 0.43] | 1/5 [0.04, 0.62] |
| implement-lru-cache (1.0.1) | 0/5 [0.00, 0.43] | 5/5 [0.57, 1.00] | 5/5 [0.57, 1.00] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] |
| mask-secrets (1.0.2) | 3/5 [0.23, 0.88] | 3/5 [0.23, 0.88] | 5/5 [0.57, 1.00] | 4/5 [0.38, 0.96] | 0/5 [0.00, 0.43] |
| merge-intervals (1.0.2) | 3/5 [0.23, 0.88] | 5/5 [0.57, 1.00] | 5/5 [0.57, 1.00] | 0/5 [0.00, 0.43] | 1/5 [0.04, 0.62] |
| paginator (1.0.2) | 2/5 [0.12, 0.77] | 5/5 [0.57, 1.00] | 5/5 [0.57, 1.00] | 5/5 [0.57, 1.00] | 0/5 [0.00, 0.43] |
| result-type (1.0.2) | 0/5 [0.00, 0.43] | 5/5 [0.57, 1.00] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] |
| sanitize-filename (1.0.2) | 4/5 [0.38, 0.96] | 3/5 [0.23, 0.88] | 4/5 [0.38, 0.96] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] |
| async-batched (1.0.2) | 0/5 [0.00, 0.43] | 3/5 [0.23, 0.88] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] |
| async-first-success (1.0.2) | 0/5 [0.00, 0.43] | 3/5 [0.23, 0.88] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] |
| async-gather-bounded (1.0.2) | 0/5 [0.00, 0.43] | 1/5 [0.04, 0.62] | 2/5 [0.12, 0.77] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] |
| fix-path-traversal (1.0.2) | 0/5 [0.00, 0.43] | 3/5 [0.23, 0.88] | 1/5 [0.04, 0.62] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] |
| grid-paths (1.0.1) | 3/5 [0.23, 0.88] | 5/5 [0.57, 1.00] | 4/5 [0.38, 0.96] | 4/5 [0.38, 0.96] | 0/5 [0.00, 0.43] |
| query-builder (1.0.2) | 1/5 [0.04, 0.62] | 5/5 [0.57, 1.00] | 5/5 [0.57, 1.00] | 0/5 [0.00, 0.43] | 1/5 [0.04, 0.62] |
| refactor-order-validation (1.0.3) | 1/5 [0.04, 0.62] | 4/5 [0.38, 0.96] | 5/5 [0.57, 1.00] | 0/5 [0.00, 0.43] | 1/5 [0.04, 0.62] |
| top-k-frequent (1.0.3) | 1/5 [0.04, 0.62] | 5/5 [0.57, 1.00] | 2/5 [0.12, 0.77] | 5/5 [0.57, 1.00] | 0/5 [0.00, 0.43] |
| toposort (1.0.2) | 0/5 [0.00, 0.43] | 4/5 [0.38, 0.96] | 3/5 [0.23, 0.88] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] |
| two-sum-indices (1.0.1) | 3/5 [0.23, 0.88] | 5/5 [0.57, 1.00] | 5/5 [0.57, 1.00] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] |
| validate-redirect-url (1.0.2) | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] |
| expression-evaluator (1.0.2) | 0/5 [0.00, 0.43] | 4/5 [0.38, 0.96] | 1/5 [0.04, 0.62] | 0/5 [0.00, 0.43] | 0/5 [0.00, 0.43] |

## Domain profiles

### gpt-oss:20b

| domain | pooled pass rate | Wilson 95% | n_eff | tasks | runs | displayable |
|---|---|---|---|---|---|---|
| api-design | 0.975 | [0.816, 0.997] | 22.9 | 5 | 25 | yes |
| async-concurrency | 0.640 | [0.445, 0.798] | 25.0 | 5 | 25 | yes |
| backend | 0.872 | [0.779, 0.929] | 76.2 | 17 | 85 | yes |
| performance | 0.950 | [0.780, 0.990] | 22.9 | 5 | 25 | yes |
| security | 0.560 | [0.371, 0.733] | 25.0 | 5 | 25 | yes |

### devstral-small-2:24b

| domain | pooled pass rate | Wilson 95% | n_eff | tasks | runs | displayable |
|---|---|---|---|---|---|---|
| api-design | 0.750 | [0.546, 0.882] | 22.9 | 5 | 25 | yes |
| async-concurrency | 0.240 | [0.115, 0.434] | 25.0 | 5 | 25 | yes |
| backend | 0.688 | [0.577, 0.781] | 76.2 | 17 | 85 | yes |
| performance | 0.675 | [0.470, 0.829] | 22.9 | 5 | 25 | yes |
| security | 0.440 | [0.267, 0.629] | 25.0 | 5 | 25 | yes |

### qwen3.5:9b

| domain | pooled pass rate | Wilson 95% | n_eff | tasks | runs | displayable |
|---|---|---|---|---|---|---|
| api-design | 0.175 | [0.070, 0.373] | 22.9 | 5 | 25 | yes |
| async-concurrency | 0.080 | [0.022, 0.250] | 25.0 | 5 | 25 | yes |
| backend | 0.368 | [0.269, 0.480] | 76.2 | 17 | 85 | yes |
| performance | 0.425 | [0.248, 0.624] | 22.9 | 5 | 25 | yes |
| security | 0.480 | [0.300, 0.665] | 25.0 | 5 | 25 | yes |

### qwen3-coder:30b

| domain | pooled pass rate | Wilson 95% | n_eff | tasks | runs | displayable |
|---|---|---|---|---|---|---|
| api-design | 0.250 | [0.118, 0.454] | 22.9 | 5 | 25 | yes |
| async-concurrency | 0.000 | [0.000, 0.133] | 25.0 | 5 | 25 | yes |
| backend | 0.040 | [0.014, 0.110] | 76.2 | 17 | 85 | yes |
| performance | 0.450 | [0.268, 0.646] | 22.9 | 5 | 25 | yes |
| security | 0.160 | [0.064, 0.347] | 25.0 | 5 | 25 | yes |

### qwen3.6:27b

| domain | pooled pass rate | Wilson 95% | n_eff | tasks | runs | displayable |
|---|---|---|---|---|---|---|
| api-design | 0.075 | [0.019, 0.253] | 22.9 | 5 | 25 | yes |
| async-concurrency | 0.000 | [0.000, 0.133] | 25.0 | 5 | 25 | yes |
| backend | 0.168 | [0.100, 0.267] | 76.2 | 17 | 85 | yes |
| performance | 0.025 | [0.003, 0.184] | 22.9 | 5 | 25 | yes |
| security | 0.000 | [0.000, 0.133] | 25.0 | 5 | 25 | yes |

## Provenance

- Campaign `phase0-modern-local-v1`, manifest `sha256:a89bf89f41c54ddb219237882af595a2bfd7109c5733bf59dbae78671b4db6d1`.
- Runtime release `phase0-integrity-v1` (7369e67e1ceb4b2a566986f247961f8a63f99567).
- Backend `ollama` at http://127.0.0.1:11434; temperature 0.8, base seed 42, request timeout 180 s; 5 repetitions per cell.
- Seed policy: ATLAS per-trial seed: the worker sets seed = base_seed + idx for repeat position idx (0..repetitions-1) before each trial (set_run_seed), so position idx of every (model, task) cell uses the same seed and a resumed position re-uses its original seed.
- Completeness receipt: complete=True, 120/120 cells, 600/600 runs, 0 problem(s).
- Launch 2026-09-27T20:55:04Z phase M1 (phase-complete): tooling `cfa9025bf804616e6b2bd2906461e382a021edcc`, app DB `<repo>/reports/phase0-modern-local.sqlite`, Ollama 0.31.1; digests: qwen3.5:9b 6488c96fa5fa, gpt-oss:20b -, devstral-small-2:24b -, qwen3-coder:30b -, qwen3.6:27b -.
- Launch 2026-09-27T23:09:55Z phase M2 (phase-complete): tooling `7d586235523d9cbc9b5dd132b249f7582016895d`, app DB `<repo>/reports/phase0-modern-local.sqlite`, Ollama 0.31.1; digests: qwen3.5:9b -, gpt-oss:20b 17052f91a42e, devstral-small-2:24b -, qwen3-coder:30b -, qwen3.6:27b -.
- Launch 2026-09-28T00:08:38Z phase M3 (phase-complete): tooling `58c8745413b4e87d114aa60733108e347dc583c6`, app DB `<repo>/reports/phase0-modern-local.sqlite`, Ollama 0.31.1; digests: qwen3.5:9b -, gpt-oss:20b -, devstral-small-2:24b 24277f07f62d, qwen3-coder:30b -, qwen3.6:27b -.
- Launch 2026-09-28T01:08:25Z phase M4 (phase-complete): tooling `4955f164912f0313af94eb72467127830541b998`, app DB `<repo>/reports/phase0-modern-local.sqlite`, Ollama 0.31.1; digests: qwen3.5:9b -, gpt-oss:20b -, devstral-small-2:24b -, qwen3-coder:30b 06c1097efce0, qwen3.6:27b -.
- Launch 2026-09-28T01:59:18Z phase M5 (phase-complete): tooling `b79ea4734ba47c5039480814d2e0d9d8f76a343a`, app DB `<repo>/reports/phase0-modern-local.sqlite`, Ollama 0.31.1; digests: qwen3.5:9b -, gpt-oss:20b -, devstral-small-2:24b -, qwen3-coder:30b -, qwen3.6:27b 9d5803d493a9.
- Model identity (pinned registry digest in the frozen manifest): qwen3.5:9b `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- Model identity (pinned registry digest in the frozen manifest): gpt-oss:20b `17052f91a42e97930aa6e28a6c6c06a983e6a58dbb00434885a0cf5313e376f7`
- Model identity (pinned registry digest in the frozen manifest): devstral-small-2:24b `24277f07f62db8f9cb68e9dfc679ea1818a7fbac47a50eff0a701d3f645b63c8`
- Model identity (pinned registry digest in the frozen manifest): qwen3-coder:30b `06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca`
- Model identity (pinned registry digest in the frozen manifest): qwen3.6:27b `9d5803d493a991af27b9441c098aa56f2ed7bbd260877f075ec09b575c049bc3`

| task | version | digest |
|---|---|---|
| escape-html | 1.0.1 | `sha256:1bfcf38552c595e2f45f0b3e0bf9aecb47846d9d155e36fad71bd552ba265525` |
| fix-binary-search | 1.0.0 | `sha256:97d42f89f91ca3ba10ee968ac43ec0281bd986ece26f76f6a7bdaef7c13484ce` |
| fix-list-dedup | 1.0.2 | `sha256:b8050c0f63f569c72738fdc8ae02ec19f5f52a23373788e1cffec4df0515f38b` |
| async-retry | 1.0.2 | `sha256:743f10eb2959463740a4c615a60af402fc9e9c650507bccdb0bba67dc4053897` |
| async-timeout | 1.0.1 | `sha256:e2d6c2616c55f1910282e2862a5b7e49709d8d4231f5c97c92bc4c40e7f104fd` |
| fix-roman-numerals | 1.0.0 | `sha256:e58739216d5cced5e441df27d4a629acf69890dddfa111e391a54e4c0ac384e6` |
| implement-lru-cache | 1.0.1 | `sha256:711a4313f541efaaad7d782730f16ac5bdc09f86babf03e59cb27e4a6ac4cc19` |
| mask-secrets | 1.0.2 | `sha256:be4619e8f0d6da8b484bc30d130eb1ad95838edb5068c206cd4d66a847293b3d` |
| merge-intervals | 1.0.2 | `sha256:413356d815870ac64bc74876b6f2a29006554e56c5d72d043bd69d154be5ab70` |
| paginator | 1.0.2 | `sha256:8455df342ed6e853cadda163e970fb098fa916472fdfe2f9353d5648c75ef4db` |
| result-type | 1.0.2 | `sha256:34098c06cd150ab3166f3c221b8c8ff4685eea2f7cdea204c90fbbd719e820a1` |
| sanitize-filename | 1.0.2 | `sha256:4546131c33d455d531d3388e629ee3257a973c58b15f81ff5ec44ab99d150574` |
| async-batched | 1.0.2 | `sha256:663be68e47533cb829a8c5add006bb24dc838d460190dccf231c4105b2520439` |
| async-first-success | 1.0.2 | `sha256:d2371fcc477cbf55f47b364925a3719a7122b525cf8ad352aa6bc560cd5e3de6` |
| async-gather-bounded | 1.0.2 | `sha256:bdcf2f0d8fc40260fba5672b6b1017d0da70d47a099e761178bbb2221a97dc54` |
| fix-path-traversal | 1.0.2 | `sha256:048d526e856035d29278fcc443c99439cacc6aed3e94a28e50c7dbdb0857d8c2` |
| grid-paths | 1.0.1 | `sha256:8bd8923b24f8f5aa16b3cace88b8139c9ae23a69cbad95f5428f679439ae9276` |
| query-builder | 1.0.2 | `sha256:fe812df540da8bdacbc65432fabbc8f6bf3ae63d4e6ad2abebf0246a544858c6` |
| refactor-order-validation | 1.0.3 | `sha256:3e2ffe535ab5f3f0ac992e376637a5289a1683ce8e0292b8193b26e2308e3972` |
| top-k-frequent | 1.0.3 | `sha256:c4fb17f874fa701173602d5e8acf50578c7622ad9473baaef1ec5d2e70936d3c` |
| toposort | 1.0.2 | `sha256:00858816e5473d96413cc1048ca43e569e378c063aa90c419b7871e1ea219251` |
| two-sum-indices | 1.0.1 | `sha256:c7005cb3b399ea7dd1f762352921e5f3588bd28e5fdfbe08515af96db63e4c7d` |
| validate-redirect-url | 1.0.2 | `sha256:c7d40bc86203bac8765553e9a2da5f72aad730a2f102cdc36ee0b215aebbac07` |
| expression-evaluator | 1.0.2 | `sha256:164d48bd040cf2c0c16865284fccd4f8b2b9358fc45e65139cf69dd4dc9cfee3` |

| cell | evaluation |
|---|---|
| qwen3.5:9b\|escape-html | b7b4d739a1294407b90ee0c0c16056f6 |
| qwen3.5:9b\|fix-binary-search | c547426684504a1fb7a60e1c7d4900f8 |
| qwen3.5:9b\|fix-list-dedup | 22ae8db0d1a24502b6c1646dc7d62e0f |
| qwen3.5:9b\|async-retry | 61266c5c9d9f4062b0fe0002346e5255 |
| qwen3.5:9b\|async-timeout | 7ae73065e29e430289d09c1b73fcaf27 |
| qwen3.5:9b\|fix-roman-numerals | 1bb5329c2dfe4e90b2bec70b0be3c213 |
| qwen3.5:9b\|implement-lru-cache | 3d06f299de6c470cb9bfb1f147dba5eb |
| qwen3.5:9b\|mask-secrets | 7254e530ca5d43af805d0ae8dc40b110 |
| qwen3.5:9b\|merge-intervals | a2bdbf3488664c0fa64e715021637221 |
| qwen3.5:9b\|paginator | 293be3b4b4284f39a95db2958aa5da70 |
| qwen3.5:9b\|result-type | 62f36d0620b44de8bd426c9e40a779a2 |
| qwen3.5:9b\|sanitize-filename | 30618e3037274d37b8033f52ff26b22f |
| qwen3.5:9b\|async-batched | 9f15138527c040f2a335ce8293356157 |
| qwen3.5:9b\|async-first-success | a78db5015bfc47a0ba7561bf08a27f46 |
| qwen3.5:9b\|async-gather-bounded | 4c77c90cc35e40f6a8ef3a71688cd25a |
| qwen3.5:9b\|fix-path-traversal | 54b0e072b95945e793e28d488a79ae40 |
| qwen3.5:9b\|grid-paths | 6e9587b51e3c4454896115b81b398261 |
| qwen3.5:9b\|query-builder | a0573744312e49da8dea8db504fcad7d |
| qwen3.5:9b\|refactor-order-validation | 441c288b27584518b793cf36f3ed8536 |
| qwen3.5:9b\|top-k-frequent | 61c0fb6ae7a241a698606b3487a7e563 |
| qwen3.5:9b\|toposort | 4d55198e001a42f2a39ff406c7e61167 |
| qwen3.5:9b\|two-sum-indices | 8a9e1b7649dd4baa9c68d7ac3c26cdbb |
| qwen3.5:9b\|validate-redirect-url | a8f8f4c95f0f4627b3a8d911c45e86d1 |
| qwen3.5:9b\|expression-evaluator | 10e911b69a1a4e0480dcc0d0934f187c |
| gpt-oss:20b\|escape-html | afcfbe631dbd44e78ec3e112a74b90d4 |
| gpt-oss:20b\|fix-binary-search | d0ffeed3f7f64cd297756187abb1afea |
| gpt-oss:20b\|fix-list-dedup | 29d97226477e4e8ca74a7745d377a09b |
| gpt-oss:20b\|async-retry | b17c7ffa2f4c471c9e5b90c02ee6d556 |
| gpt-oss:20b\|async-timeout | cf9f4a1fd1a44687bb292f1ae0816293 |
| gpt-oss:20b\|fix-roman-numerals | 3a2e535f872048e0a9b2934cea740b61 |
| gpt-oss:20b\|implement-lru-cache | bc7b948eaa8c4903ac126999925caff5 |
| gpt-oss:20b\|mask-secrets | 0745d339082c47ccb92af3590bb9f855 |
| gpt-oss:20b\|merge-intervals | dc8d3be121d74c248e84b54eca921907 |
| gpt-oss:20b\|paginator | b178da7ee39b4ddc8ab2f1cdece29ff1 |
| gpt-oss:20b\|result-type | 53ffd353d6954e398dae929fabd7da40 |
| gpt-oss:20b\|sanitize-filename | de881f853b2e422d8fb960b46f42e927 |
| gpt-oss:20b\|async-batched | 3d9b6d3933394550b065533639165d0f |
| gpt-oss:20b\|async-first-success | f74badacd54047d5b5526d1c75bfc5de |
| gpt-oss:20b\|async-gather-bounded | 30f570756c124b188a0d3505c7466635 |
| gpt-oss:20b\|fix-path-traversal | 8677105c7d054dfd93b5ca4e715558a9 |
| gpt-oss:20b\|grid-paths | 8e3e92665d964ee186dac136320fa158 |
| gpt-oss:20b\|query-builder | 133193e4e1c24fa2b83e92d5b848ee4a |
| gpt-oss:20b\|refactor-order-validation | 6aceb644d2d142659c4e5662ef5e090e |
| gpt-oss:20b\|top-k-frequent | 9cb1f6e0cdbe4fd3a6045dc88346eb31 |
| gpt-oss:20b\|toposort | 59a4057de28e4cb29ec8ebfc9e5d443a |
| gpt-oss:20b\|two-sum-indices | 6a59d50d0132469dae57dc4a846c2282 |
| gpt-oss:20b\|validate-redirect-url | 9777a932aaaf45f2bad2665a2f7b05c1 |
| gpt-oss:20b\|expression-evaluator | 3fb7391bbb7d49c7b89eb827253a1de3 |
| devstral-small-2:24b\|escape-html | e44074b7eec74e26a66c28a27e2806fc |
| devstral-small-2:24b\|fix-binary-search | 2c82e6783b3343b085a714ecb0a8854b |
| devstral-small-2:24b\|fix-list-dedup | 0a5ae9f0b68644f7a4b45d846cfa714f |
| devstral-small-2:24b\|async-retry | 5444476b17624948bd9eebecc391a51a |
| devstral-small-2:24b\|async-timeout | eaf3d5ebf5834d30882ced865a0c63f7 |
| devstral-small-2:24b\|fix-roman-numerals | 8d0f8535b7c445e3928bcc7403d86962 |
| devstral-small-2:24b\|implement-lru-cache | b4f44d83551a4da6a907900b39ceccc9 |
| devstral-small-2:24b\|mask-secrets | d50f80f5e9624dc9bcc53009bbf14fef |
| devstral-small-2:24b\|merge-intervals | 12c4c6714e144382affb84364b58f1a2 |
| devstral-small-2:24b\|paginator | 07801af6cc734e08bedfcf54ed28c475 |
| devstral-small-2:24b\|result-type | 0854091dab254c5c906ada6841085826 |
| devstral-small-2:24b\|sanitize-filename | 911d7945ccac430bbe3802b5cd5e1e32 |
| devstral-small-2:24b\|async-batched | 672089d6acc1456f9df927d0bd634430 |
| devstral-small-2:24b\|async-first-success | ee7f0c6d5766463483561ff595068897 |
| devstral-small-2:24b\|async-gather-bounded | a2e75dd441d84e43b6e29aba02dccb3f |
| devstral-small-2:24b\|fix-path-traversal | decc2327b6ed4024988dba67a4da5757 |
| devstral-small-2:24b\|grid-paths | d5b05599e7cb464399046cadf2ba96d9 |
| devstral-small-2:24b\|query-builder | c7c082eac43c4d8cb83fdb415d894a61 |
| devstral-small-2:24b\|refactor-order-validation | e3a88306e14d406a928eaed1fb4b550d |
| devstral-small-2:24b\|top-k-frequent | c9be1767fbbf4f61bee6af9c3d6f534c |
| devstral-small-2:24b\|toposort | 6f6b39f3c1294f0b9d3b3151f8164ab4 |
| devstral-small-2:24b\|two-sum-indices | 19269aa3a65544beb722164d54093cb2 |
| devstral-small-2:24b\|validate-redirect-url | 2abbeafb20ab4c1cb95bc2052e36e191 |
| devstral-small-2:24b\|expression-evaluator | 6c96c4f530b945189e383b2abcca0b76 |
| qwen3-coder:30b\|escape-html | 506b4955ca5c4967a9758b6ce37b805f |
| qwen3-coder:30b\|fix-binary-search | 9da0c8b2d57044da915267a84264df57 |
| qwen3-coder:30b\|fix-list-dedup | 58f409c3a32243198fb2d9fd70e5d0e2 |
| qwen3-coder:30b\|async-retry | 969bf18d65604cdd85ae23caea1157b6 |
| qwen3-coder:30b\|async-timeout | 168d5faa50244fc99c12d9957cad0b4e |
| qwen3-coder:30b\|fix-roman-numerals | 3e6b8b544ed744819be25ba9927adfe9 |
| qwen3-coder:30b\|implement-lru-cache | d3744031909c4fbe9dd5caa666a513fb |
| qwen3-coder:30b\|mask-secrets | 493f42c589e34d8e9f752aa4270859ed |
| qwen3-coder:30b\|merge-intervals | 697f7dbd7cc24908b5474e6297e35029 |
| qwen3-coder:30b\|paginator | d58ec5bbb23642c3b1cee400a061574c |
| qwen3-coder:30b\|result-type | ede929347c6c4bfb93276bde9ec06615 |
| qwen3-coder:30b\|sanitize-filename | 4b96a48afe20402a9fab8a23110068c1 |
| qwen3-coder:30b\|async-batched | 95cf0f6e175943f2be51df1ea0d5bc2a |
| qwen3-coder:30b\|async-first-success | 29be2ea16b7f470aa002fb065b647f54 |
| qwen3-coder:30b\|async-gather-bounded | c3265526c531475990a2dcc3d8e06d08 |
| qwen3-coder:30b\|fix-path-traversal | dd5b2ca2c5784646bbf27e2d3ac45e09 |
| qwen3-coder:30b\|grid-paths | d0bfe28d0f7947f199bfcb4ccb51eed5 |
| qwen3-coder:30b\|query-builder | 7868180aab0a4678bb9b315a0940e8ce |
| qwen3-coder:30b\|refactor-order-validation | c7b80a7ba74642da8a72a3bd4d8c279e |
| qwen3-coder:30b\|top-k-frequent | a35079ce7e9a4448bf33d66a88677314 |
| qwen3-coder:30b\|toposort | 36332ac1ec964d5eb30edf18c014c4d0 |
| qwen3-coder:30b\|two-sum-indices | bca2471bc6bf4768a2700facb85c2d18 |
| qwen3-coder:30b\|validate-redirect-url | ba46cf78804046e0b2f243ee3b06470e |
| qwen3-coder:30b\|expression-evaluator | 5167442c49d34c30ab336c440dd2bbc4 |
| qwen3.6:27b\|escape-html | 334347ea3beb49818206b564674d6255 |
| qwen3.6:27b\|fix-binary-search | 8d2fdef5417246d78801d30a98f9360c |
| qwen3.6:27b\|fix-list-dedup | f6d2be037858470982197119dce71fef |
| qwen3.6:27b\|async-retry | bb04332196be495b93e50ac3575243ba |
| qwen3.6:27b\|async-timeout | cdc27b7a23464d8d91260ddabc3ce769 |
| qwen3.6:27b\|fix-roman-numerals | 92e202c997f04702a1a6f2d8dd60c2a0 |
| qwen3.6:27b\|implement-lru-cache | b62102cd675e42ceba5a6dd7101bd0ad |
| qwen3.6:27b\|mask-secrets | feece6324f7448d3b721306816ade7e9 |
| qwen3.6:27b\|merge-intervals | 28ea6eaad82547c1b03f38ec3d6db5be |
| qwen3.6:27b\|paginator | f822994c18b747a5ac26d3770e8df5aa |
| qwen3.6:27b\|result-type | c0f0128d47224d97a27358eecdf4e6c6 |
| qwen3.6:27b\|sanitize-filename | 174ab3dad82c40ef8dddd45bc18c084f |
| qwen3.6:27b\|async-batched | a119cc24d0054e5389a70c5fbb1d2467 |
| qwen3.6:27b\|async-first-success | c22f15beaa7b440dbaf06e0601ca4652 |
| qwen3.6:27b\|async-gather-bounded | 213fad06856d431d81178fbc4fba2a2b |
| qwen3.6:27b\|fix-path-traversal | 8745966ad791481f830f905276ef6286 |
| qwen3.6:27b\|grid-paths | ccfbe3c479694a06959590ac3dc2a1b4 |
| qwen3.6:27b\|query-builder | 6ab0d9233b794b139753eb442b0434e5 |
| qwen3.6:27b\|refactor-order-validation | 8a1f005f930f4884b82e14f8047a3e1c |
| qwen3.6:27b\|top-k-frequent | 0fe52f6e407b4256bed422196d95836b |
| qwen3.6:27b\|toposort | fa4d7ff2d519453d8c6fa0c3fb3a22b7 |
| qwen3.6:27b\|two-sum-indices | f77e7f848aee453caa71d9256f817827 |
| qwen3.6:27b\|validate-redirect-url | 169c75683861495a83a8c495355dc1ab |
| qwen3.6:27b\|expression-evaluator | ea04cce6264b4268a91eb32b84d327f1 |
