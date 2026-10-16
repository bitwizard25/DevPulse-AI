# Durable execution, memory and context upgrade

Approved scope: durable gateway jobs, restart recovery, bounded retry/cancellation, persistent provider circuits, searchable local Markdown/code, and model-aware estimated context budgets. Preserve domain/application/infrastructure/interfaces dependency direction. No MCP/GitHub/language expansion in this round.

Privacy decision: persist bounded redacted review snapshots for 24 hours, never raw source, credentials or vault mappings. Run deterministic checks before snapshot persistence. Markdown remains authoritative; indexes are derived and project-isolated.

Defaults: one FIFO worker; 100 outstanding jobs; 5-second heartbeat; three execution attempts with jittered exponential backoff; provider circuit cooldown 30 seconds; 8192 context tokens, 2048 output tokens, 1024 safety tokens; eight memory/skill and eight code chunks; 5000 tracked files/20 MB indexing cap. Conservative UTF-8 token estimate is explicitly labeled. Mandatory source/rules must fit intact.

## Execution ledger

- [x] 1. SQLite migrations/backups and atomic job storage: ownership, claim fencing, heartbeat, expiry, coalescing, cancellation, result inspection. Real SQLite tests pass, including v2 backup preservation and concurrent claims.
- [x] 2. Immutable prepared review snapshots, durable worker, persistent circuit policy and classified retries. 42 tests pass; gateway wiring/process-kill coverage follows in steps 5–6.
- [x] 3. Project-isolated FTS5 memory/code index with provenance and deterministic bounded retrieval.
- [x] 4. Context planning and token budgets, snapshot identity and provider output/context limits.
- [x] 5. Gateway/CLI jobs API, detached/blocking workflows, memory search/reindex, context preview and shutdown.
- [x] 6. Regression/integration/process-kill tests, independent review, package/build/installed smoke, docs.

Current baseline: uncommitted existing MVP in the user's checkout. Preserve all existing files; no worktree or commits that would hide the user's current work. Implement inline. Final review gets a separate reviewer under the executing-plans skill.

## Decisions and evidence

65 tests pass on Windows with Python 3.12.14 and 3.14.7. Includes an actual gateway process kill, source mutation, replay of identical redacted input, five-second heartbeat, manual retry, reserved HTTP control capacity, project isolation and version 1/2 backup preservation.

Independent reviewer found three material issues. All reproduced with failing regression tests and fixed: configured credential seeding for standalone memory/context entry points; reserved request capacity for controls while compatibility reviews wait; re-scrubbing indexed paths after later secret discovery. No additional blocking findings.

Implementation clarification: exclusive gateway process ownership authorizes recovery of prior worker identities; heartbeats provide liveness visibility, and are not permission to steal an ongoing provider request. Job snapshots expire logically; historical backups require separate retention. Remote inference is at least once after crashes, so repeat billing is possible.
