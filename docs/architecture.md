# Architecture

DevPulse uses a local gateway to coordinate review jobs and SQLite to persist operational state. Human-maintained Markdown holds durable project knowledge. This follows the broad ideas of a local control plane and explicit memory described in [OpenClaw gateway architecture](https://docs.openclaw.ai/concepts/architecture) and [memory documentation](https://docs.openclaw.ai/concepts/memory); it is an independent implementation, not an OpenClaw protocol clone.

The task-first coding harness reuses the provider, context and SQLite adapters. Its terminal process owns the interactive model/tool loop so file and command approvals stay attached to the user's terminal. It stores redacted session turns in the shared SQLite state database and takes a process lock for one active agent turn. The gateway remains the owner of durable review jobs and provider circuits. A future gateway RPC can own interactive turns once it can stream approval requests back to the terminal; this MVP does not imply that the interactive tool loop is gateway-managed.

## Dependency direction

```text
interfaces (CLI / terminal / HTTP)
                 |
                 v
application (review workflow / routing policies / ports)
                 |
                 v
domain (configuration values / findings / privacy / checks)

infrastructure implements application ports
bootstrap.py wires concrete adapters at process startup
```

The domain imports no application, infrastructure or presentation modules. The application imports domain rules and its own Protocol contracts; it does not import SQLite, Git, HTTP or concrete adapters. `tests/test_architecture.py` guards these boundaries. No dependency injection framework is needed.

## Repository map

| Directory | Responsibility |
| --- | --- |
| `devpulse/domain/agent.py`, `agent_prompts.py` | Strict single-call model decision contract and concise task prompt optimized for smaller models |
| `devpulse/application/` | Review and task orchestration, durable worker, job use cases, MCP service, context selection/budgets and provider routing; typed ports for adapters |
| `devpulse/infrastructure/` | OS telemetry, agent integration adapters (Claude, Antigravity, Codex), bounded project tools, SQLite queue/index/circuit/session adapters and migrations, locks, Git/Markdown/configuration access and HTTP transport |
| `devpulse/interfaces/` | Task-first terminal loop, focused command handlers (`review`, `jobs`, `models`, `verify`, `mcp`, `integrate`), safe terminal rendering and authenticated loopback gateway |
| `devpulse/bootstrap.py` | Composition root that constructs the review engine with concrete adapters |
| `tests/` | Behavior, integration and architecture boundary tests; no live account needed |

## Review lifecycle

1. An interface supplies the project and review options.
2. Source/context adapters read bounded inputs. A request-local vault protects keys and scrubs content; a forked index vault prevents unrelated detections from polluting source findings. Derived indexing rescrubs text and paths after all documents have been scanned.
3. Pure local checks run on original Python in memory. Retrieval supplies redacted provenance chunks; the context planner preserves mandatory source/rules and fits optional excerpts within model/token/byte budgets.
4. Preparation emits an immutable redacted snapshot. Gateway submission commits it and the job atomically. The single worker claims through a transaction, starts an attempt session, and checks the exact cache. Direct/offline review executes synchronously through the same engine.
5. Untrusted model findings are validated, re-scrubbed, combined with deterministic findings and bounded.
6. Redacted results enter the cache and session record. Presentation renders a safe report and maps severity to exit status.

## Task session lifecycle

1. `devpulse` in a TTY opens the task prompt; `devpulse run "..."` provides a one-turn interface. First-run setup selects a provider source and initializes project rules/memory.
2. The harness loads redacted prior messages, prepares bounded project rules/memory/code context, and gives the model a strict JSON decision contract plus a small typed tool catalog.
3. Tool calls are validated and routed through project-scoped adapters. Paths cannot escape the repository; secret and generated areas are excluded. Writes display a diff and commands display their argv; each requires terminal approval. A nested `AGENTS.md` is surfaced to the model before a write in that directory is allowed.
4. Every model response, user turn, and tool result is scrubbed before local transcript storage. Context is bounded to the smallest configured provider input budget and old in-memory messages are dropped first.
5. The user can resume the active project session, start a new one, clear the transcript, or inspect session IDs. The agent never claims verification succeeded unless a command or deterministic verifier returned success.

The terminal harness is a single-agent runtime in this release. Session records live in the common SQLite database, while the foreground CLI owns interactive execution and approvals. Background tool jobs, subagents, and remote channels are deferred.

Persisted snapshots contain redacted prompts and precomputed findings, with configuration names and opaque original-input identities. Raw code, credential values, provider error bodies and vault mappings are not intentionally persisted. Snapshot payloads expire after 24 hours; history/results are separate. Operational reviews are not silently promoted into project knowledge or injected as memory.

## Ownership, concurrency and failure

State initialization is protected across processes. Version 5 migrations verify FTS5 and back up existing state before any schema change. Each operation uses a short transaction/connection. Job claims use `BEGIN IMMEDIATE`, ownership fencing, timestamps and FIFO insertion tie-breaking. Future schema versions fail closed. The gateway has an exclusive process lock and atomic discovery descriptor. Eight HTTP handlers allow only four blocking review waits; job controls retain capacity.

Attempt sessions record process ownership for legacy/direct history. Durable jobs use a unique worker identity and five-second heartbeats. Only a new exclusive gateway owner performs restart recovery; its acquired process lock establishes that the prior gateway cannot still own the worker. Recovered jobs retain snapshot/expiry/attempt counts, and stale owners cannot complete them. Heartbeats provide active-attempt visibility rather than authorizing a second worker to steal a running HTTP request.

Cancellation is cooperative across the routing boundary and checked before further provider calls or publication. Shutdown stops claiming jobs and drains the active attempt. A crash can repeat remote inference; exactly-once billing is outside the queue's contract. Back up `identity.key` and a consistent SQLite backup together; do not copy a live WAL database file alone. Expiry does not erase historical backups.

Provider transport has timeouts, bounded bytes, no redirects and no remote plaintext HTTP. Transient failures are eligible for ordered failover and bounded scheduled retries. Circuit cooldowns persist across restarts. Gateway environment is a startup snapshot; credentials are not sent through job-control payloads. Missing keys and malformed review JSON are nonretryable.

## Retrieval and context contracts

`MemoryIndex` stores project-isolated redacted chunks and fingerprints; Markdown/Git remain authoritative. Refresh reconciles edits and deletions. It scans tracked and non-ignored untracked Git paths, then excludes credential, generated, binary and oversized files under the 5000-path/20-MB bounds. Retrieval uses quoted lexical FTS queries with bounded results and deterministic path/line ties, never semantic cache equivalence. Task context prioritizes the newest tool evidence and evicts older results if required to fit; it fails clearly if even the latest result cannot fit.

`TokenCounter` is replaceable. Review planning uses a conservative UTF-8 estimator, includes the serialized user message and shared system prompt, and reserves output/framing tokens. The task harness budgets serialized JSON at two bytes per configured input token; this intentionally leaves room for smaller-model context while avoiding the previous one-byte-per-token underuse. These are estimates, not tokenizer counts. Mandatory source/rules remain complete; optional material uses bounded excerpts with provenance and omission reasons. The preview exposes these decisions without inference. Index, prompt and budget versions participate in review cache identity.

## Extending the MVP

- Add a provider by implementing `ModelTransport`; preserve strict review validation. Add protocol fixture tests and a separate opt-in live smoke test.
- Add storage by implementing `StateStore`; preserve cache TTL and session failure semantics.
- Add syntax checks as pure domain functions. Do not execute reviewed code as part of syntax validation.
- Add another entry point by composing the same application service. Keep framework/request objects out of the application.
- Add semantic retrieval only with measured correctness criteria; semantic similarity must not imply code-review equivalence.

Before adding dependencies or new abstractions, identify the boundary they solve and exercise that behavior in a test. Avoid importing adapters into the domain/application to make a new feature convenient.
