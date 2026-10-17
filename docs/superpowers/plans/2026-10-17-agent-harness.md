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
- [x] Full suite: 126 tests passed, one platform-specific skip. Ruff check/format and installed wheel smoke passed.
- [ ] Live Ollama quality benchmark across representative small models. Fixture protocol tests establish tool-loop behavior, not model reasoning quality or Codex/Claude parity.
- [x] Create `Downloads/project.md` and `Downloads/decision.md` after all code, package and repository-document checks are complete.

Implementation boundary: interactive task turns run in the foreground process so approvals can be shown in the user's terminal. The existing local gateway remains responsible for durable review jobs and provider circuits; making it the owner of interactive turns requires a terminal event/approval RPC and is a later phase. This first harness release supports Ollama and OpenAI-compatible providers only, stores at most 200 messages per session, and uses a shared process lock for one active task turn.

### Ollama connectivity correction

- Reproduced the backendcode failure: the configured loopback Ollama service was unreachable; no executable was found on PATH or in standard installation directories. A configured model name did not prove inference was available.
- Added distinct connection/timeout recovery messages and a bounded, no-inference `doctor` probe for Ollama service/model availability.
- Regression tests were observed failing before implementation. The full suite then passed 135 tests with one platform-specific skip; Ruff and the installed-wheel smoke passed.
- Reinstalled the global build after closing the terminal session and stopping its idle editor MCP helper. Verified the global `doctor` and task command now report the unavailable Ollama service explicitly. Live inference remains unverified until a server and model are available.
