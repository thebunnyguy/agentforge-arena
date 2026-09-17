# AgentForge Arena — Updates to Make

Use this file to keep track of requested product updates. Add each new item as its own numbered section with a status, reference, requested behavior, and completion checks.

## 1. Download individual evaluation reports as Markdown

**Status:** Planned

**Reference format:** [`reports/qwen3.5-9b-evaluation-2026-09-17.md`](reports/qwen3.5-9b-evaluation-2026-09-17.md)

### Current behavior

The Reports page offers a JSON export of current aggregate data and can regenerate the HTML leaderboard. It does not offer a downloadable Markdown report for a selected evaluation job. The Qwen 3.5 9B report linked above was extracted manually from the job's stored results.

### Requested behavior

Add a **Download report (.md)** option for an individual evaluation in the app, including its completed job results page and/or Reports page. The downloaded file should use the **same section order, Markdown layout, tables, and level of detail** as the reference report:

1. Report title, model name, job ID and status, run times, and source records.
2. Result summary: functional passes and rate, 95% Wilson interval, mean continuous score, valid attempts, timeouts, nonpassing attempts, voided attempts, and tasks passed at least once.
3. Evaluation setup: backend, selected tasks, repeat count, seed, temperature, request timeout, scoring version, and relevant provenance limits.
4. Per-task results table: task, task version, passes, timeouts, and mean score.
5. Observations supported by the saved results, followed by interpretation and limitations.
6. Source records that make the numbers traceable to the selected job.
7. An appendix explaining **what each selected task does and consists of**, its editable package and time limit, plus the evaluation terms and conditions: fresh attempts, allowed edits, grading, passes, partial scores, timeouts, infrastructure voids, and interpretation limits.

The report must be generated from the **selected job's persisted runs** and the corresponding task specifications. Reuse the existing scoring and confidence calculations; do not recalculate them with different frontend formulas. Do not mix in another job's results or present the global leaderboard as the selected job's report. Label incomplete or canceled jobs clearly if their saved attempts can be downloaded. Distinguish missing stored evidence from zero or failure.

### Completion checks

- A user can choose an evaluation and download a `.md` file directly in the browser; the filename identifies the model and job or date.
- The downloaded report follows the reference Markdown format, including the task-description and evaluation-terms appendix.
- The headline totals reconcile with that job's counters and run records; per-task rows reconcile with its attempts.
- The download remains available when the app is reopened and the job is loaded from the database.
- An automated check covers the report contents, job scoping, and the browser download action.
