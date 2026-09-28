# Model receipt - gpt-oss 20B (`gpt-oss:20b`), phase0-modern-local-v1 phase M2

- Accepted runs: **120 / 120** (24 tasks x 5 repetitions), validation complete.
- Passes: 96 / 120 (pass rate 0.800, Wilson 95% [0.720, 0.862]); timeouts 0; agent errors 0; voided 0.
- Model digest 17052f91a42e97930aa6e28a6c6c06a983e6a58dbb00434885a0cf5313e376f7 (matches the frozen pin: True); Ollama 0.31.1; quantization MXFP4, 20.9B parameters.
- AgentForge release `phase0-integrity-v1` (7369e67e1ceb4b2a566986f247961f8a63f99567); manifest sha256:a89bf89f41c54ddb219237882af595a2bfd7109c5733bf59dbae78671b4db6d1.
- Generation: temperature 0.8, base seed 42, request timeout 180 s.
- Window: 2026-09-27T23:09:55Z -> 2026-09-27T23:49:23Z.

| task (version) | evaluation | passed/valid | timeouts |
|---|---|---|---|
| escape-html (1.0.1) | `afcfbe631dbd44e78ec3e112a74b90d4` | 5/5 | 0 |
| fix-binary-search (1.0.0) | `d0ffeed3f7f64cd297756187abb1afea` | 4/5 | 0 |
| fix-list-dedup (1.0.2) | `29d97226477e4e8ca74a7745d377a09b` | 5/5 | 0 |
| async-retry (1.0.2) | `b17c7ffa2f4c471c9e5b90c02ee6d556` | 5/5 | 0 |
| async-timeout (1.0.1) | `cf9f4a1fd1a44687bb292f1ae0816293` | 4/5 | 0 |
| fix-roman-numerals (1.0.0) | `3a2e535f872048e0a9b2934cea740b61` | 5/5 | 0 |
| implement-lru-cache (1.0.1) | `bc7b948eaa8c4903ac126999925caff5` | 5/5 | 0 |
| mask-secrets (1.0.2) | `0745d339082c47ccb92af3590bb9f855` | 3/5 | 0 |
| merge-intervals (1.0.2) | `dc8d3be121d74c248e84b54eca921907` | 5/5 | 0 |
| paginator (1.0.2) | `b178da7ee39b4ddc8ab2f1cdece29ff1` | 5/5 | 0 |
| result-type (1.0.2) | `53ffd353d6954e398dae929fabd7da40` | 5/5 | 0 |
| sanitize-filename (1.0.2) | `de881f853b2e422d8fb960b46f42e927` | 3/5 | 0 |
| async-batched (1.0.2) | `3d9b6d3933394550b065533639165d0f` | 3/5 | 0 |
| async-first-success (1.0.2) | `f74badacd54047d5b5526d1c75bfc5de` | 3/5 | 0 |
| async-gather-bounded (1.0.2) | `30f570756c124b188a0d3505c7466635` | 1/5 | 0 |
| fix-path-traversal (1.0.2) | `8677105c7d054dfd93b5ca4e715558a9` | 3/5 | 0 |
| grid-paths (1.0.1) | `8e3e92665d964ee186dac136320fa158` | 5/5 | 0 |
| query-builder (1.0.2) | `133193e4e1c24fa2b83e92d5b848ee4a` | 5/5 | 0 |
| refactor-order-validation (1.0.3) | `6aceb644d2d142659c4e5662ef5e090e` | 4/5 | 0 |
| top-k-frequent (1.0.3) | `9cb1f6e0cdbe4fd3a6045dc88346eb31` | 5/5 | 0 |
| toposort (1.0.2) | `59a4057de28e4cb29ec8ebfc9e5d443a` | 4/5 | 0 |
| two-sum-indices (1.0.1) | `6a59d50d0132469dae57dc4a846c2282` | 5/5 | 0 |
| validate-redirect-url (1.0.2) | `9777a932aaaf45f2bad2665a2f7b05c1` | 0/5 | 0 |
| expression-evaluator (1.0.2) | `3fb7391bbb7d49c7b89eb827253a1de3` | 4/5 | 0 |
