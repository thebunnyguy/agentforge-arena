# Model receipt - Qwen3.6 27B (`qwen3.6:27b`), phase0-modern-local-v1 phase M5

- Accepted runs: **120 / 120** (24 tasks x 5 repetitions), validation complete.
- Passes: 11 / 120 (pass rate 0.092, Wilson 95% [0.052, 0.157]); timeouts 105; agent errors 0; voided 0.
- Model digest 9d5803d493a991af27b9441c098aa56f2ed7bbd260877f075ec09b575c049bc3 (matches the frozen pin: True); Ollama 0.31.1; quantization Q4_K_M, 27.3B parameters.
- AgentForge release `phase0-integrity-v1` (7369e67e1ceb4b2a566986f247961f8a63f99567); manifest sha256:a89bf89f41c54ddb219237882af595a2bfd7109c5733bf59dbae78671b4db6d1.
- Generation: temperature 0.8, base seed 42, request timeout 180 s.
- Window: 2026-09-28T01:59:19Z -> 2026-09-28T07:21:15Z.

| task (version) | evaluation | passed/valid | timeouts |
|---|---|---|---|
| escape-html (1.0.1) | `334347ea3beb49818206b564674d6255` | 0/5 | 5 |
| fix-binary-search (1.0.0) | `8d2fdef5417246d78801d30a98f9360c` | 4/5 | 1 |
| fix-list-dedup (1.0.2) | `f6d2be037858470982197119dce71fef` | 3/5 | 2 |
| async-retry (1.0.2) | `bb04332196be495b93e50ac3575243ba` | 0/5 | 5 |
| async-timeout (1.0.1) | `cdc27b7a23464d8d91260ddabc3ce769` | 0/5 | 5 |
| fix-roman-numerals (1.0.0) | `92e202c997f04702a1a6f2d8dd60c2a0` | 1/5 | 4 |
| implement-lru-cache (1.0.1) | `b62102cd675e42ceba5a6dd7101bd0ad` | 0/5 | 5 |
| mask-secrets (1.0.2) | `feece6324f7448d3b721306816ade7e9` | 0/5 | 5 |
| merge-intervals (1.0.2) | `28ea6eaad82547c1b03f38ec3d6db5be` | 1/5 | 4 |
| paginator (1.0.2) | `f822994c18b747a5ac26d3770e8df5aa` | 0/5 | 5 |
| result-type (1.0.2) | `c0f0128d47224d97a27358eecdf4e6c6` | 0/5 | 5 |
| sanitize-filename (1.0.2) | `174ab3dad82c40ef8dddd45bc18c084f` | 0/5 | 5 |
| async-batched (1.0.2) | `a119cc24d0054e5389a70c5fbb1d2467` | 0/5 | 1 |
| async-first-success (1.0.2) | `c22f15beaa7b440dbaf06e0601ca4652` | 0/5 | 5 |
| async-gather-bounded (1.0.2) | `213fad06856d431d81178fbc4fba2a2b` | 0/5 | 5 |
| fix-path-traversal (1.0.2) | `8745966ad791481f830f905276ef6286` | 0/5 | 5 |
| grid-paths (1.0.1) | `ccfbe3c479694a06959590ac3dc2a1b4` | 0/5 | 5 |
| query-builder (1.0.2) | `6ab0d9233b794b139753eb442b0434e5` | 1/5 | 4 |
| refactor-order-validation (1.0.3) | `8a1f005f930f4884b82e14f8047a3e1c` | 1/5 | 4 |
| top-k-frequent (1.0.3) | `0fe52f6e407b4256bed422196d95836b` | 0/5 | 5 |
| toposort (1.0.2) | `fa4d7ff2d519453d8c6fa0c3fb3a22b7` | 0/5 | 5 |
| two-sum-indices (1.0.1) | `f77e7f848aee453caa71d9256f817827` | 0/5 | 5 |
| validate-redirect-url (1.0.2) | `169c75683861495a83a8c495355dc1ab` | 0/5 | 5 |
| expression-evaluator (1.0.2) | `ea04cce6264b4268a91eb32b84d327f1` | 0/5 | 5 |
