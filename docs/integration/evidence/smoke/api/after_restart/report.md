# AgentForge Evaluation Report

- Schema version: `1`
- Evaluation: `2a9413656539405c854529bbcba230e2`
- Model: `smoke-unseen-060701`
- Provider: `mock`
- Status: `succeeded`
- Mode: `fresh`

## Evaluation

- Created at: `2026-09-19 00:37:01`
- Started at: `2026-09-19 00:37:01`
- Finished at: `2026-09-19 00:37:09`
- Backend: `{"base_url":null,"kind":"mock"}`
- Parameters: `{"backend":{"base_url":null,"kind":"mock"},"base_seed":1000,"model":"smoke-unseen-060701","name":null,"repeats":2,"request_timeout_s":180,"source_evaluation_id":null,"temperature":0.6}`
- Generation: `{"base_seed":1000,"request_timeout_s":180,"seed_provenance":"unavailable","temperature":0.6,"timeout_provenance":"not_applicable"}`

## Summary

- Total: 6
- Completed: 6
- Passed: 6
- Failed: 0
- Voided: 0
- Reused: 0
- Incomplete: 0
- Unavailable: 0

## Counter semantics

- Total: canonical requested evaluation trial rows
- Completed: completed rows, including reused evidence
- Passed: fresh completed rows with a usable non-voided passing score
- Failed: fresh completed rows with a usable non-voided failing score
- Voided: fresh completed rows with a usable voided score
- Reused: completed rows explicitly linked to prior evidence
- Incomplete: rows not in completed trial state
- Unavailable: rows without a usable outcome, including incomplete or missing score evidence

## Task snapshots

- `sanitize-filename` @ `1.0.2` (`sha256:4546131c33d455d531d3388e629ee3257a973c58b15f81ff5ec44ab99d150574`)
- `toposort` @ `1.0.2` (`sha256:00858816e5473d96413cc1048ca43e569e378c063aa90c419b7871e1ea219251`)
- `validate-redirect-url` @ `1.0.2` (`sha256:c7d40bc86203bac8765553e9a2da5f72aad730a2f102cdc36ee0b215aebbac07`)

## Trials

### `sanitize-filename` @ `1.0.2` — trial 0

- Run ID: `1221`
- Evidence: `fresh`
- Trial state: `completed`
- Result: `PASS`
- Outcome status: `valid`
- Functional pass: `true`
- Voided: `false`
- Score: `1.0`
- Artifacts: `complete`
- Comparability: `comparable`
- Origin evaluation: `2a9413656539405c854529bbcba230e2`

### `sanitize-filename` @ `1.0.2` — trial 1

- Run ID: `1222`
- Evidence: `fresh`
- Trial state: `completed`
- Result: `PASS`
- Outcome status: `valid`
- Functional pass: `true`
- Voided: `false`
- Score: `1.0`
- Artifacts: `complete`
- Comparability: `comparable`
- Origin evaluation: `2a9413656539405c854529bbcba230e2`

### `toposort` @ `1.0.2` — trial 0

- Run ID: `1223`
- Evidence: `fresh`
- Trial state: `completed`
- Result: `PASS`
- Outcome status: `valid`
- Functional pass: `true`
- Voided: `false`
- Score: `1.0`
- Artifacts: `complete`
- Comparability: `comparable`
- Origin evaluation: `2a9413656539405c854529bbcba230e2`

### `toposort` @ `1.0.2` — trial 1

- Run ID: `1224`
- Evidence: `fresh`
- Trial state: `completed`
- Result: `PASS`
- Outcome status: `valid`
- Functional pass: `true`
- Voided: `false`
- Score: `1.0`
- Artifacts: `complete`
- Comparability: `comparable`
- Origin evaluation: `2a9413656539405c854529bbcba230e2`

### `validate-redirect-url` @ `1.0.2` — trial 0

- Run ID: `1225`
- Evidence: `fresh`
- Trial state: `completed`
- Result: `PASS`
- Outcome status: `valid`
- Functional pass: `true`
- Voided: `false`
- Score: `1.0`
- Artifacts: `complete`
- Comparability: `comparable`
- Origin evaluation: `2a9413656539405c854529bbcba230e2`

### `validate-redirect-url` @ `1.0.2` — trial 1

- Run ID: `1226`
- Evidence: `fresh`
- Trial state: `completed`
- Result: `PASS`
- Outcome status: `valid`
- Functional pass: `true`
- Voided: `false`
- Score: `1.0`
- Artifacts: `complete`
- Comparability: `comparable`
- Origin evaluation: `2a9413656539405c854529bbcba230e2`

## Limitations

- None recorded.
