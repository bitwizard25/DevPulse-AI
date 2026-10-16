# Architecture

DevPulse uses a single local gateway to coordinate review work and SQLite to persist operational state. Human-maintained Markdown holds durable project knowledge. This follows the broad ideas of a local control plane and explicit memory described in [OpenClaw gateway architecture](https://docs.openclaw.ai/concepts/architecture) and [memory documentation](https://docs.openclaw.ai/concepts/memory); it is an independent implementation, not an OpenClaw protocol clone.

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
| `devpulse/domain/` | Typed jobs/snapshots, hardware entities and model rating formulas, MCP JSON-RPC schemas, pure configuration validation, secret masking, Python AST rules, model-result validation and output limits |
| `devpulse/application/` | Review preparation/execution, durable worker, job use cases, MCP application service, context selection/budgets and provider routing; typed ports for adapters |
| `devpulse/infrastructure/` | OS telemetry hardware probe and Ollama tags fetcher, agent integration adapters (Claude, Antigravity, Codex), SQLite queue/index/circuit adapters and migrations, locks, Git/Markdown/configuration access, conservative token counter and bounded HTTP transport |
| `devpulse/interfaces/` | Argument parser, focused command handlers (`review`, `jobs`, `models`, `verify`, `mcp`, `integrate`), safe terminal rendering, terminal dashboard and authenticated loopback gateway |
| `devpulse/bootstrap.py` | Composition root that constructs the review engine with concrete adapters |
| `tests/` | Behavior, integration and architecture boundary tests; no live account needed |

## Review lifecycle

1. An interface supplies the project and review options.
2. Source/context adapters read bounded inputs. A request-local vault protects keys and scrubs content; a forked index vault prevents unrelated detections from polluting source findings. Derived indexing rescrubs text and paths after all documents have been scanned.
3. Pure local checks run on original Python in memory. Retrieval supplies redacted provenance chunks; the context planner preserves mandatory source/rules and fits optional excerpts within model/token/byte budgets.
4. Preparation emits an immutable redacted snapshot. Gateway submission commits it and the job atomically. The single worker claims through a transaction, starts an attempt session, and checks the exact cache. Direct/offline review executes synchronously through the same engine.
5. Untrusted model findings are validated, re-scrubbed, combined with deterministic findings and bounded.
6. Redacted results enter the cache and session record. Presentation renders a safe report and maps severity to exit status.

Persisted snapshots contain redacted prompts and precomputed findings, with configuration names and opaque original-input identities. Raw code, credential values, provider error bodies and vault mappings are not intentionally persisted. Snapshot payloads expire after 24 hours; history/results are separate. Operational reviews are not silently promoted into project knowledge or injected as memory.

## Ownership, concurrency and failure

State initialization is protected across processes. Version 3 migrations verify FTS5 and back up existing state before any schema change. Each operation uses a short transaction/connection. Job claims use `BEGIN IMMEDIATE`, ownership fencing, timestamps and FIFO insertion tie-breaking. Future schema versions fail closed. The gateway has an exclusive process lock and atomic discovery descriptor. Eight HTTP handlers allow only four blocking review waits; job controls retain capacity.

Attempt sessions record process ownership for legacy/direct history. Durable jobs use a unique worker identity and five-second heartbeats. Only a new exclusive gateway owner performs restart recovery; its acquired process lock establishes that the prior gateway cannot still own the worker. Recovered jobs retain snapshot/expiry/attempt counts, and stale owners cannot complete them. Heartbeats provide active-attempt visibility rather than authorizing a second worker to steal a running HTTP request.

Cancellation is cooperative across the routing boundary and checked before further provider calls or publication. Shutdown stops claiming jobs and drains the active attempt. A crash can repeat remote inference; exactly-once billing is outside the queue's contract. Back up `identity.key` and a consistent SQLite backup together; do not copy a live WAL database file alone. Expiry does not erase historical backups.

Provider transport has timeouts, bounded bytes, no redirects and no remote plaintext HTTP. Transient failures are eligible for ordered failover and bounded scheduled retries. Circuit cooldowns persist across restarts. Gateway environment is a startup snapshot; credentials are not sent through job-control payloads. Missing keys and malformed review JSON are nonretryable.

## Retrieval and context contracts

`MemoryIndex` stores project-isolated redacted chunks and fingerprints; Markdown/Git remain authoritative. Refresh reconciles edits and deletions. Retrieval uses quoted lexical FTS queries with bounded results and deterministic path/line ties, never semantic cache equivalence. Paths stay within the project, and tracked credential/generated/binary files are excluded. Index skip diagnostics are sampled and counted so metadata cannot overflow review transport limits.

`TokenCounter` is replaceable. The initial conservative UTF-8 estimator is labeled estimated, includes the serialized user message and shared system prompt, and reserves output/framing tokens. `ContextPlanner` uses the smallest eligible provider input allowance. Mandatory source/rules remain complete; optional material uses bounded excerpts with provenance and omission reasons. The preview exposes these decisions without inference. Index, prompt and budget versions participate in cache identity.

## Extending the MVP

- Add a provider by implementing `ModelTransport`; preserve strict review validation. Add protocol fixture tests and a separate opt-in live smoke test.
- Add storage by implementing `StateStore`; preserve cache TTL and session failure semantics.
- Add syntax checks as pure domain functions. Do not execute reviewed code as part of syntax validation.
- Add another entry point by composing the same application service. Keep framework/request objects out of the application.
- Add semantic retrieval only with measured correctness criteria; semantic similarity must not imply code-review equivalence.

Before adding dependencies or new abstractions, identify the boundary they solve and exercise that behavior in a test. Avoid importing adapters into the domain/application to make a new feature convenient.
