# DevPulse task-first terminal harness

## Product decision

DevPulse should feel like a coding agent when launched in a terminal: the developer describes an outcome in plain language, and the harness inspects the repository, plans the work, acts within the project, and reports what it changed and verified. The existing explicit commands remain available for reviews, jobs, memory, MCP, integrations, and operations.

The first-run path should establish sensible defaults automatically. It detects the project, Git state, installed local inference, existing provider configuration, and agent instruction files. It asks only for missing information that blocks the requested work. It must not make the user choose among every feature before the first useful task.

## OpenClaw patterns adopted

OpenClaw documents a persistent gateway as the source of truth for sessions and routing, an explicit agent workspace contract, bootstrap context, and skills that load only when needed. DevPulse already has the local gateway, durable jobs, SQLite state, Markdown rules, and indexed memory. The harness should build on those services rather than creating a second state owner.

DevPulse adopts these ideas at a smaller coding-agent scale:

- Durable SQLite sessions and turn records, scoped to a project identity; the foreground terminal owns interactive model/tool execution and approvals while the existing gateway owns review jobs and provider circuits.
- A compact workspace bootstrap assembled from `AGENTS.md`, `CLAUDE.md`, `.devpulse/RULES.md`, and relevant memory, with clear precedence and bounded context.
- A task loop that chooses from a small typed tool catalog: inspect files, search, read, propose/apply an in-project patch, run a bounded verification command, and invoke DevPulse review. Small-model reliability is improved with concise prompts, one tool call per model response, and newest-result-preserving context compaction.
- Skills as on-demand task procedures with YAML frontmatter; only matching skills enter the prompt.
- Visible progress, tool calls, diffs, and verification results in the terminal.

## Safety and behavior contract

- All paths resolve inside the selected project. Ignore secrets, generated output, dependency trees, and binary files.
- Provider requests pass through the existing redaction boundary. Persisted turn content is redacted and bounded; credentials and vault mappings never enter session storage.
- Edits are limited to project files and are shown as diffs. The user controls the execution policy; the initial policy defaults to asking before commands with side effects or network access.
- Read-only discovery and deterministic checks can run without approval. A review result is advisory unless a deterministic verifier reports a blocker.
- A turn has a bounded tool-call count, wall-clock deadline, output size, and context budget. The agent cannot claim a check passed unless it ran and received a successful result.
- If model output is malformed, the loop reports the error and preserves the session; it does not guess at tool arguments.
- Interruption records the current turn state so the user can resume or inspect it.

## MVP interaction

First launch:

```text
$ devpulse
DevPulse found a Python project and a running local Ollama model (qwen2.5-coder:7b).
I will keep changes inside this repository and ask before risky commands.
What should we work on?
> Find why login retries never stop and fix it
```

Subsequent launch resumes the latest project session. The user can type a task, ` /status`, `/clear`, `/help`, or `/quit`. Non-interactive use stays scriptable through `devpulse run "..." --json` and existing subcommands.

## Delivery boundary

The first harness release is a single-user, local coding agent. It does not add chat channels, remote workers, plugin marketplaces, unrestricted shell access, browser automation, automatic GitHub writes, semantic embeddings, native Anthropic/Gemini agent adapters, or multi-agent orchestration. It does not claim equivalent task success to Codex or Claude Code; live model quality must be measured on a representative evaluation set. Those capabilities require separate policy and operational work.

The core acceptance path is: launch in a configured repository, state a task, see repository discovery and a short plan, review a proposed change, let the harness apply it, and see actual verification output. The session remains inspectable after interruption or restart.
