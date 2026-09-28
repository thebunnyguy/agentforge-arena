# Model receipt - Devstral Small 2 24B (`devstral-small-2:24b`), phase0-modern-local-v1 phase M3

- Accepted runs: **120 / 120** (24 tasks x 5 repetitions), validation complete.
- Passes: 71 / 120 (pass rate 0.592, Wilson 95% [0.502, 0.675]); timeouts 5; agent errors 0; voided 0.
- Model digest 24277f07f62db8f9cb68e9dfc679ea1818a7fbac47a50eff0a701d3f645b63c8 (matches the frozen pin: True); Ollama 0.31.1; quantization Q4_K_M, 24.0B parameters.
- AgentForge release `phase0-integrity-v1` (7369e67e1ceb4b2a566986f247961f8a63f99567); manifest sha256:a89bf89f41c54ddb219237882af595a2bfd7109c5733bf59dbae78671b4db6d1.
- Generation: temperature 0.8, base seed 42, request timeout 180 s.
- Window: 2026-09-28T00:08:38Z -> 2026-09-28T00:53:15Z.

| task (version) | evaluation | passed/valid | timeouts |
|---|---|---|---|
| escape-html (1.0.1) | `e44074b7eec74e26a66c28a27e2806fc` | 1/5 | 0 |
| fix-binary-search (1.0.0) | `2c82e6783b3343b085a714ecb0a8854b` | 5/5 | 0 |
| fix-list-dedup (1.0.2) | `0a5ae9f0b68644f7a4b45d846cfa714f` | 4/5 | 0 |
| async-retry (1.0.2) | `5444476b17624948bd9eebecc391a51a` | 0/5 | 0 |
| async-timeout (1.0.1) | `eaf3d5ebf5834d30882ced865a0c63f7` | 4/5 | 0 |
| fix-roman-numerals (1.0.0) | `8d0f8535b7c445e3928bcc7403d86962` | 5/5 | 0 |
| implement-lru-cache (1.0.1) | `b4f44d83551a4da6a907900b39ceccc9` | 5/5 | 0 |
| mask-secrets (1.0.2) | `d50f80f5e9624dc9bcc53009bbf14fef` | 5/5 | 0 |
| merge-intervals (1.0.2) | `12c4c6714e144382affb84364b58f1a2` | 5/5 | 0 |
| paginator (1.0.2) | `07801af6cc734e08bedfcf54ed28c475` | 5/5 | 0 |
| result-type (1.0.2) | `0854091dab254c5c906ada6841085826` | 0/5 | 0 |
| sanitize-filename (1.0.2) | `911d7945ccac430bbe3802b5cd5e1e32` | 4/5 | 0 |
| async-batched (1.0.2) | `672089d6acc1456f9df927d0bd634430` | 0/5 | 0 |
| async-first-success (1.0.2) | `ee7f0c6d5766463483561ff595068897` | 0/5 | 0 |
| async-gather-bounded (1.0.2) | `a2e75dd441d84e43b6e29aba02dccb3f` | 2/5 | 2 |
| fix-path-traversal (1.0.2) | `decc2327b6ed4024988dba67a4da5757` | 1/5 | 0 |
| grid-paths (1.0.1) | `d5b05599e7cb464399046cadf2ba96d9` | 4/5 | 0 |
| query-builder (1.0.2) | `c7c082eac43c4d8cb83fdb415d894a61` | 5/5 | 0 |
| refactor-order-validation (1.0.3) | `e3a88306e14d406a928eaed1fb4b550d` | 5/5 | 0 |
| top-k-frequent (1.0.3) | `c9be1767fbbf4f61bee6af9c3d6f534c` | 2/5 | 3 |
| toposort (1.0.2) | `6f6b39f3c1294f0b9d3b3151f8164ab4` | 3/5 | 0 |
| two-sum-indices (1.0.1) | `19269aa3a65544beb722164d54093cb2` | 5/5 | 0 |
| validate-redirect-url (1.0.2) | `2abbeafb20ab4c1cb95bc2052e36e191` | 0/5 | 0 |
| expression-evaluator (1.0.2) | `6c96c4f530b945189e383b2abcca0b76` | 1/5 | 0 |
