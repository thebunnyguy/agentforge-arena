# Model receipt - Qwen 3.5 9B (`qwen3.5:9b`), phase0-modern-local-v1 phase M1

- Accepted runs: **120 / 120** (24 tasks x 5 repetitions), validation complete.
- Passes: 40 / 120 (pass rate 0.333, Wilson 95% [0.255, 0.422]); timeouts 30; agent errors 0; voided 0.
- Model digest 6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7 (matches the frozen pin: True); Ollama 0.31.1; quantization Q4_K_M, 9.7B parameters.
- AgentForge release `phase0-integrity-v1` (7369e67e1ceb4b2a566986f247961f8a63f99567); manifest sha256:a89bf89f41c54ddb219237882af595a2bfd7109c5733bf59dbae78671b4db6d1.
- Generation: temperature 0.8, base seed 42, request timeout 180 s.
- Window: 2026-09-27T20:55:04Z -> 2026-09-27T22:50:06Z.

| task (version) | evaluation | passed/valid | timeouts |
|---|---|---|---|
| escape-html (1.0.1) | `b7b4d739a1294407b90ee0c0c16056f6` | 5/5 | 0 |
| fix-binary-search (1.0.0) | `c547426684504a1fb7a60e1c7d4900f8` | 4/5 | 0 |
| fix-list-dedup (1.0.2) | `22ae8db0d1a24502b6c1646dc7d62e0f` | 4/5 | 1 |
| async-retry (1.0.2) | `61266c5c9d9f4062b0fe0002346e5255` | 0/5 | 3 |
| async-timeout (1.0.1) | `7ae73065e29e430289d09c1b73fcaf27` | 2/5 | 1 |
| fix-roman-numerals (1.0.0) | `1bb5329c2dfe4e90b2bec70b0be3c213` | 4/5 | 1 |
| implement-lru-cache (1.0.1) | `3d06f299de6c470cb9bfb1f147dba5eb` | 0/5 | 1 |
| mask-secrets (1.0.2) | `7254e530ca5d43af805d0ae8dc40b110` | 3/5 | 0 |
| merge-intervals (1.0.2) | `a2bdbf3488664c0fa64e715021637221` | 3/5 | 0 |
| paginator (1.0.2) | `293be3b4b4284f39a95db2958aa5da70` | 2/5 | 2 |
| result-type (1.0.2) | `62f36d0620b44de8bd426c9e40a779a2` | 0/5 | 2 |
| sanitize-filename (1.0.2) | `30618e3037274d37b8033f52ff26b22f` | 4/5 | 1 |
| async-batched (1.0.2) | `9f15138527c040f2a335ce8293356157` | 0/5 | 0 |
| async-first-success (1.0.2) | `a78db5015bfc47a0ba7561bf08a27f46` | 0/5 | 3 |
| async-gather-bounded (1.0.2) | `4c77c90cc35e40f6a8ef3a71688cd25a` | 0/5 | 3 |
| fix-path-traversal (1.0.2) | `54b0e072b95945e793e28d488a79ae40` | 0/5 | 0 |
| grid-paths (1.0.1) | `6e9587b51e3c4454896115b81b398261` | 3/5 | 2 |
| query-builder (1.0.2) | `a0573744312e49da8dea8db504fcad7d` | 1/5 | 0 |
| refactor-order-validation (1.0.3) | `441c288b27584518b793cf36f3ed8536` | 1/5 | 1 |
| top-k-frequent (1.0.3) | `61c0fb6ae7a241a698606b3487a7e563` | 1/5 | 3 |
| toposort (1.0.2) | `4d55198e001a42f2a39ff406c7e61167` | 0/5 | 3 |
| two-sum-indices (1.0.1) | `8a9e1b7649dd4baa9c68d7ac3c26cdbb` | 3/5 | 2 |
| validate-redirect-url (1.0.2) | `a8f8f4c95f0f4627b3a8d911c45e86d1` | 0/5 | 0 |
| expression-evaluator (1.0.2) | `10e911b69a1a4e0480dcc0d0934f187c` | 0/5 | 1 |
