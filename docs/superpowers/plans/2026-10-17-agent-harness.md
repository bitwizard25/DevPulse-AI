# Task-First Agent Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make DevPulse a task-first terminal coding harness with simple setup, bounded agent tools, durable resumable sessions, and visible verification.

**Architecture:** Preserve the existing domain/application/infrastructure/interfaces direction. Add a domain model and policies for turns/tools, an application agent loop behind ports, infrastructure adapters for project operations and persisted sessions, and a thin terminal interface. Reuse the existing secret vault, context planner, provider circuits, and SQLite database. Keep interactive approvals in the foreground terminal; the gateway continues to own durable review jobs.

**Tech Stack:** Python 3.11+, stdlib argparse/SQLite/subprocess, current provider adapters, Markdown rules and skills.

**Spec:** `docs/product/agent-first-harness.md`

## Global Constraints

- Keep the project dependency-free and compatible with Python 3.11+.
- Preserve existing explicit CLI commands and their JSON contracts.
- Keep all writes inside the selected project and all provider calls behind redaction.
- Persist only redacted, bounded session records; never persist credential values or vault mappings.
- Every agent action has bounded input, output, calls, and time; risky shell actions require the configured approval policy.
- Do not claim checks passed without an observed successful command result.
- Persist session and job state in the shared SQLite store. The foreground CLI owns interactive turns and approvals; the gateway owns review jobs and provider circuits.

## Review Focus

- Prompt injection in repository instructions, source files, memory, or skills must not override tool policy.
- Traversal and symlink escapes must not allow tools to read or write outside the project.
- Malformed tool-call JSON must fail closed without executing partial arguments.
- Cancellation or gateway restart must not leave false successful turn results.
- Logs, prompts, tool output, errors, and persisted turn history must not expose secrets.

## Repository Map

- `devpulse/domain/agent.py`: immutable turn/tool values and limits.
- `devpulse/application/agent.py`: prompt assembly, tool loop, cancellation, and orchestration ports.
- `devpulse/infrastructure/agent_tools.py`: safe project file/search/command adapters.
- `devpulse/infrastructure/agent_sessions.py`: SQLite conversation and turn persistence/migration.
- `devpulse/infrastructure/providers.py`: general text/tool-call transport alongside strict review transport.
- `devpulse/bootstrap.py`: compose the task runtime.
- `devpulse/interfaces/agent.py`: terminal chat loop and command rendering.
- `devpulse/interfaces/parser.py`, `cli.py`: task-first entry points and backward-compatible commands.
- `devpulse/interfaces/setup.py`: minimal auto-detect setup.
- `docs/architecture.md`, `README.md`: user behavior and architecture.

## Delivery Tasks

### Task 1: Provider-neutral agent turn contract and prompts

Define strict JSON schemas for model decisions (`message`, `tool_calls`, `final`, `summary`) and tool results. Provide one core harness prompt, one short repo-inspection prompt, and on-demand skill injection. Reuse the existing router and request-local vault. Bound malformed output and recursion.

### Task 2: Safe project tool catalog

Implement list/search/read, unified diff proposal and apply, bounded command execution, and deterministic verify/review tools. Enforce project-root containment, symlink checks, exclusions, byte/time limits, and policy approval before side-effect commands.

### Task 3: Durable sessions and turns

Add versioned SQLite schema for sessions, messages, tool events, and turn state. Use project-scoped opaque identities; store only bounded redacted data. Provide resume, status, clear/archive, and interruption recovery.

### Task 4: Task loop and session ownership

Implement a bounded agent orchestration use case that reads session context, assembles project instructions and relevant skills/memory, invokes the model, validates tool decisions, runs tools, records progress, and returns a final response. Serialize active turns with a process lock. The foreground CLI owns interactive execution; the shared SQLite database owns durable session records.

### Task 5: Task-first CLI and setup

Make `devpulse` open the conversation in a TTY and accept a task. Add `devpulse run <task>` for non-interactive use, with `--json`, `--session`, and timeout handling. Detect repository instructions/providers automatically and ask only for missing credentials or policy decisions. Preserve current subcommands.

### Task 6: Packaging, docs, and end-to-end acceptance

Document session/privacy/tool policy and run actual installed-wheel task flows using a deterministic local model fixture, including restart/resume and a real verification command.

## Execution Ledger

### Resumed standalone coding-agent work

Ruling: continue in the current checkout with its existing uncommitted harness changes, as requested by the user. Preserve the user's edits; no automatic commit or push.

Ruling: the requested product is a standalone coding agent using configurable Ollama/API inference. Prioritize reliable context, file operations and real task execution before terminal polish or additional integrations. The foreground process continues to own interactive tools; gateway execution requires a separate approval/event transport.

Baseline: 89 tests discovered, one setup-module import error after the old launcher was removed. Previous harness work had no functional coverage.

- [x] Pinned task/instruction context, bounded structured tool-result compaction, decision validation.
- [x] Ranged reads, precise edits, stale-file checks, safe path exclusions, preserved file metadata.
- [x] Durable turn/action journal, interrupted-turn recovery without automatic mutation replay.
- [x] Repository instructions before scoped writes, session permission modes, provider-independent end-to-end task flow.
- [x] Full suite, independent review and installed wheel acceptance; Downloads handoff docs are intentionally created last.

- [x] OpenClaw docs inspected; task-first harness spec and delivery boundary recorded.
- [x] Task 1: typed model decisions, task prompt, provider failover, bounded model context.
- [x] Task 2: project-scoped list/read/search/write/command/verify tools with path checks and approvals.
- [x] Task 3: version 5 SQLite sessions and redacted bounded transcript storage.
- [x] Task 4: task loop, relevant context, serialized foreground turns, and progress output.
- [x] Task 5: task-first TTY entry, one-choice setup, `run` command, resume/new/clear/status, explicit non-interactive permissions.
- [x] Task 6 docs and packaging metadata; Ruff formatting and lint pass.
- [x] Installed wheel acceptance: both Ollama and OpenAI-compatible fixture protocols completed a real edit, command verification and session resume.
- [x] Independent review findings fixed: action IDs scrubbed from later model context, newest tool evidence retained under context pressure, and nested `AGENTS.md` surfaced before edits.
- [x] Small-model efficiency pass: one action per response, concise tool-focused prompts, two-byte-per-input-token serialized budget, and newest-result-preserving compaction.
- [x] Expose the existing read-only whole-project AI review engine as an agent tool for natural-language repository audit requests; add runtime composition and task-loop regression coverage.
- [x] Full suite: 126 tests passed, one platform-specific skip. Ruff check/format and installed wheel smoke passed.
- [x] Live Ollama smoke on `phi3.5:3.8b`: a natural-language whole-project review of an isolated SQL-injection fixture used the direct review route and reported `billing.py:5` with a concrete explanation. This is one smoke case, not a representative quality benchmark or Codex/Claude parity measurement.
- [ ] Live task-quality benchmark across representative coding/review tasks and small models. Fixture protocol tests establish tool-loop behavior, not comparative success rates or Codex/Claude parity.
- [x] Create `Downloads/project.md` and `Downloads/decision.md` after all code, package and repository-document checks are complete.

Implementation boundary: interactive task turns run in the foreground process so approvals can be shown in the user's terminal. The existing local gateway remains responsible for durable review jobs and provider circuits; making it the owner of interactive turns requires a terminal event/approval RPC and is a later phase. This first harness release supports Ollama and OpenAI-compatible providers only, stores at most 200 messages per session, and uses a shared process lock for one active task turn.

### Ollama connectivity correction

- Reproduced the backendcode failure: the configured loopback Ollama service was unreachable; no executable was found on PATH or in standard installation directories. A configured model name did not prove inference was available.
- Added distinct connection/timeout recovery messages and a bounded, no-inference `doctor` probe for Ollama service/model availability.
- Regression tests were observed failing before implementation. The full suite then passed 135 tests with one platform-specific skip; Ruff and the installed-wheel smoke passed.
- Reinstalled the global build after closing the terminal session and stopping its idle editor MCP helper. Verified the global `doctor` and task command now report the unavailable Ollama service explicitly. Live inference remains unverified until a server and model are available.

### Online provider picker and global package update (2026-10-17)

- Added native OpenAI-compatible, Anthropic Messages API and Google Gemini GenerateContent adapters for both reviews and task sessions. API key values are only read from the selected environment variable.
- Added setup choices for OpenAI, Anthropic and Google Gemini, including provider-specific model, endpoint and environment-variable defaults. Re-running `devpulse setup` keeps rules/memory and updates provider selection; offline selection clears only the provider list.
- Set the default OpenAI model to `gpt-6-luna-fast` for online setup and `init --provider openai-compatible`; Anthropic and Google presets currently use `claude-sonnet-5` and `gemini-3.8-flash`.
- Bumped package version to 0.3.2 and reinstalled globally. Confirmed global `devpulse --version` and provider choices in `devpulse init --help`.
- Did not run the full test suite or Ruff for this update. No live cloud request was possible without API keys. Live Ollama responded to a short connectivity prompt in 144.09 seconds, with 110.11 seconds spent loading; this is not a task-quality measurement.

### Task reliability and API onboarding follow-up (2026-10-18)

- Added held-out behavioral checks and isolated real-CLI evaluations for bug fixing, a feature spanning files, test execution, and project review. A completion claim or unrelated successful command cannot pass the test-execution case.
- Reproduced and fixed overly broad review routing: requests such as `check all tests`, targeted file reviews, explanations and negated review instructions remain task-model requests. Explicit project audits still use the direct review engine.
- First live Phi3.5 test-execution attempt failed before any action: `Agent decision must contain message, tool_calls and final only.` This is evidence of an unresolved small-model decision-contract failure, not a successful task. Evaluation cleanup initially left a SQLite reader open on Windows; the reader now closes explicitly.
- User-requested onboarding change: capture missing cloud keys with hidden input, activate immediately, and save in the Windows user environment. Existing interactive cloud projects also request missing keys. Provider transport, secret protection and diagnostics share the same credential resolver; no key is written to project files or persisted transcripts.
- Other platforms retain process-local key capture and externally managed environment variables. Windows registry persistence is the user's requested mechanism; no credential-bearing subprocess command is used.

- API onboarding candidate v0.3.4 passed 159 tests (one platform skip), Ruff, installed-wheel acceptance and a disposable real Windows user-environment save/read check. The global replacement was denied while an existing DevPulse executable remained open; no claim of global installation success was made.

### Folder eligibility and consent (2026-10-18)

- User requirement: detect Git and coding content before indexing; ask before indexing coding folders without Git; ordinary-file folders must not be indexed and must report that they are not coding repositories. Markdown documentation is an eligible content type per the user's instruction.
- Added bounded name-only project inspection, persistent per-project consent, and enforcement inside the SQLite index adapter. Existing index/search callers cannot bypass the gate by running headlessly. Interactive entry points request consent; scripts may explicitly approve with `memory reindex --approve-non-git`. Declines remove derived content for that project.
- Schema version 6 adds index permissions; a regression verifies version-5 backup and existing cache preservation. Retrieval/cache fixtures now establish Git coding repositories so they exercise the eligible path instead of silently approving non-Git folders.
- Ollama now receives the decision/tool-argument JSON schema. The next live Phi3.5 run produced parseable responses but still failed the test-execution task: it repeated a natural-language file filter and ended without running tests. Structural validity is improved; task effectiveness is not yet satisfactory and parity remains unproven.
- The proposed per-file AI review cache and dependency-aware invalidation are still follow-up work. Current indexing already fingerprints files and avoids rewriting unchanged chunks; this is not yet a dependency-aware review cache.

- Final v0.3.5 verification: 170 tests passed with one platform skip; Ruff and diff checks passed. The rebuilt wheel passed installed-environment acceptance for reviews, durable jobs, cancellation, gateway lifecycle and Ollama/API fixture coding tasks with verification and resume. This fixture acceptance is separate from the failing live Phi3.5 task evaluation.
- Global replacement remained locked by the existing v0.3.3 launcher and Python child. The failed installer had partially removed that environment; restored its previous package from the current Git HEAD release archive without replacing active executables, then verified global `devpulse --version` from outside the checkout returns `0.3.3`. The new v0.3.5 wheel is ready but is not globally installed until that session closes.
