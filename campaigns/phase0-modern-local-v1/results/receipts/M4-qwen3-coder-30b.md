# Model receipt - Qwen3-Coder 30B-A3B (`qwen3-coder:30b`), phase0-modern-local-v1 phase M4

- Accepted runs: **120 / 120** (24 tasks x 5 repetitions), validation complete.
- Passes: 18 / 120 (pass rate 0.150, Wilson 95% [0.097, 0.225]); timeouts 0; agent errors 0; voided 0.
- Model digest 06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca (matches the frozen pin: True); Ollama 0.31.1; quantization Q4_K_M, 30.5B parameters.
- AgentForge release `phase0-integrity-v1` (7369e67e1ceb4b2a566986f247961f8a63f99567); manifest sha256:a89bf89f41c54ddb219237882af595a2bfd7109c5733bf59dbae78671b4db6d1.
- Generation: temperature 0.8, base seed 42, request timeout 180 s.
- Window: 2026-09-28T01:08:25Z -> 2026-09-28T01:20:51Z.

| task (version) | evaluation | passed/valid | timeouts |
|---|---|---|---|
| escape-html (1.0.1) | `506b4955ca5c4967a9758b6ce37b805f` | 0/5 | 0 |
| fix-binary-search (1.0.0) | `9da0c8b2d57044da915267a84264df57` | 0/5 | 0 |
| fix-list-dedup (1.0.2) | `58f409c3a32243198fb2d9fd70e5d0e2` | 0/5 | 0 |
| async-retry (1.0.2) | `969bf18d65604cdd85ae23caea1157b6` | 0/5 | 0 |
| async-timeout (1.0.1) | `168d5faa50244fc99c12d9957cad0b4e` | 0/5 | 0 |
| fix-roman-numerals (1.0.0) | `3e6b8b544ed744819be25ba9927adfe9` | 0/5 | 0 |
| implement-lru-cache (1.0.1) | `d3744031909c4fbe9dd5caa666a513fb` | 0/5 | 0 |
| mask-secrets (1.0.2) | `493f42c589e34d8e9f752aa4270859ed` | 4/5 | 0 |
| merge-intervals (1.0.2) | `697f7dbd7cc24908b5474e6297e35029` | 0/5 | 0 |
| paginator (1.0.2) | `d58ec5bbb23642c3b1cee400a061574c` | 5/5 | 0 |
| result-type (1.0.2) | `ede929347c6c4bfb93276bde9ec06615` | 0/5 | 0 |
| sanitize-filename (1.0.2) | `4b96a48afe20402a9fab8a23110068c1` | 0/5 | 0 |
| async-batched (1.0.2) | `95cf0f6e175943f2be51df1ea0d5bc2a` | 0/5 | 0 |
| async-first-success (1.0.2) | `29be2ea16b7f470aa002fb065b647f54` | 0/5 | 0 |
| async-gather-bounded (1.0.2) | `c3265526c531475990a2dcc3d8e06d08` | 0/5 | 0 |
| fix-path-traversal (1.0.2) | `dd5b2ca2c5784646bbf27e2d3ac45e09` | 0/5 | 0 |
| grid-paths (1.0.1) | `d0bfe28d0f7947f199bfcb4ccb51eed5` | 4/5 | 0 |
| query-builder (1.0.2) | `7868180aab0a4678bb9b315a0940e8ce` | 0/5 | 0 |
| refactor-order-validation (1.0.3) | `c7b80a7ba74642da8a72a3bd4d8c279e` | 0/5 | 0 |
| top-k-frequent (1.0.3) | `a35079ce7e9a4448bf33d66a88677314` | 5/5 | 0 |
| toposort (1.0.2) | `36332ac1ec964d5eb30edf18c014c4d0` | 0/5 | 0 |
| two-sum-indices (1.0.1) | `bca2471bc6bf4768a2700facb85c2d18` | 0/5 | 0 |
| validate-redirect-url (1.0.2) | `ba46cf78804046e0b2f243ee3b06470e` | 0/5 | 0 |
| expression-evaluator (1.0.2) | `5167442c49d34c30ab336c440dd2bbc4` | 0/5 | 0 |
