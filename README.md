# DevPulse AI

A local-first terminal coding harness and code reviewer with a single-process gateway, durable sessions, and explicit project memory. Python 3.11+, Git, no Docker and no required runtime packages.

The review commands remain read-only. The task harness can propose project file changes and commands, but asks before writing or executing them. It does not post to GitHub.

## Install from this checkout

```sh
uv tool install .
# Or: pipx install .
devpulse --help
```

The distribution is named `devpulse-ai`; the executable is `devpulse`. It has not been published to PyPI. To run without installation, use `python -m devpulse` from this checkout.

## Work by describing a task

Inside a configured repository, launch `devpulse` and describe the result you want. DevPulse loads project rules, relevant memory and code, then uses a bounded tool loop to inspect files, search, propose edits and run checks. It shows progress as it works. Before each file write or command, it displays the diff or command and asks for approval.

```sh
devpulse
# Describe the task at the prompt
devpulse run "Find why login retries never stop and fix it" --allow-edits --allow-commands --json
```

The task harness supports Ollama, OpenAI, Anthropic and Google Gemini. First launch asks whether to use a local model, an online API (then asks which provider), or offline checks. New OpenAI setups default to `gpt-6-luna-fast`. Each project has an active resumable local session. `devpulse` resumes it on the next launch; `/new` starts another, `/clear` deletes the current transcript, `/status` shows its ID and model, and `/quit` exits. Use `devpulse run --session SESSION_ID "..."` to resume a specific session. Conversation text is secret-scrubbed and stored in the local SQLite state database. Non-interactive runs deny writes and commands unless `--allow-edits` and `--allow-commands` are explicitly provided.

## First review without a model

Inside your Git repository:

```sh
devpulse init --provider offline
git add your_file.py
devpulse review --offline
devpulse review --offline --file your_file.py --json
```

Offline mode performs Python parsing, flags direct `eval`/`exec` calls and `subprocess` calls with literal `shell=True`, checks for potential secrets, and flags diffs above 500 changed lines. It is deliberately labeled as deterministic checking, not an AI review or comprehensive security audit. Files in other languages receive secret scanning; they do not receive syntax validation yet.

Default input is the staged diff. `--worktree` reviews tracked unstaged changes; untracked files require `--file` or staging. Use the repository root as your project directory for diff reviews. Whole-file reviews work without Git.

Exit codes: `0` no finding at the selected failure level; `1` findings meet that level; `2` configuration/runtime error; `130` interrupted. Default is `--fail-on error`; use `--fail-on warning` in stricter CI or `--fail-on none` for reporting.

## Ollama

Start Ollama and pull your chosen coding model separately. Then initialize a fresh project:

```sh
devpulse init --provider ollama --model YOUR_INSTALLED_MODEL
devpulse review
```

`init` preserves existing files. If you initialized offline first, edit `.devpulse/config.json` to add a provider. DevPulse does not install models or claim a model will fit your hardware.

If a model request fails, run `devpulse doctor`. It probes Ollama's model list with a five-second timeout and reports `ready`, `unavailable`, `model_missing`, or `invalid_response`, without loading a model or sending source code. A configured model name alone does not mean Ollama is installed or running. Start an installed service with `ollama serve`; download a missing model separately with `ollama pull MODEL`. Connection failures and slow-model timeouts have separate recovery messages. Cloud credentials are checked locally; `doctor` does not send cloud inference requests.

## Online providers and failover

The setup wizard offers OpenAI, Anthropic and Google Gemini. It configures native APIs for each service and stores only the environment variable name in project config. Set the key in your shell before running DevPulse:

```sh
devpulse init --provider openai-compatible
devpulse init --provider anthropic
devpulse init --provider google
```

The default model IDs are `gpt-6-luna-fast`, `claude-sonnet-5`, and `gemini-3.8-flash`. Override them with `--model`. Their default key variables are `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GOOGLE_API_KEY`. For example, in PowerShell set `$env:OPENAI_API_KEY = "your-key"` for the current terminal session. `devpulse setup` opens the provider picker again and updates the active provider while keeping project rules and memory.

For failover, edit `.devpulse/config.json`:

```json
{
  "providers": [
    {
      "name": "local",
      "kind": "ollama",
      "model": "YOUR_INSTALLED_MODEL",
      "base_url": "http://127.0.0.1:11434",
      "api_key_env": "",
      "timeout": 90
    },
    {
      "name": "cloud",
      "kind": "anthropic",
      "model": "YOUR_CLOUD_MODEL",
      "base_url": "https://api.anthropic.com/v1",
      "api_key_env": "ANTHROPIC_API_KEY",
      "timeout": 90
    }
  ],
  "context_bytes": 24000,
  "cache_ttl": 86400
}
```

Providers are tried in order. Three transient failures open a persistent circuit for 30 seconds in the shared gateway. Durable jobs allow three attempts with jittered exponential backoff for connection failures, timeouts, HTTP 408/429 and 5xx responses. Invalid model output and missing credentials fail without automatic retry. `review --chaos --no-cache` simulates failure of the first provider; configure a second provider to see successful failover. `--direct` runs AI review in the CLI process instead, with process-local circuits.

Provider configuration also accepts `context_window_tokens` (default 8192), `output_tokens` (2048), and `safety_tokens` (1024). Ollama receives explicit `num_ctx`/`num_predict` settings. The gateway inherits credentials when it starts. After changing an environment key, stop and restart it from that shell.

## State, memory, context

```sh
devpulse memory add "Use parameterized SQL for database queries."
devpulse memory show
devpulse memory search "database adapters" --json
devpulse memory reindex
devpulse context --json
devpulse context --file your_file.py --json
devpulse sessions --json
devpulse cache clear
devpulse prune --days 30
```

- `.devpulse/RULES.md`: review conventions, included first.
- `.devpulse/MEMORY.md`: explicitly recorded decisions, retrieved by relevance, with a bounded fallback when no query matches.
- `.devpulse/skills/*/SKILL.md`: up to 20 review skills indexed in deterministic path order. Markdown and YAML frontmatter are review guidance; they cannot execute tools.
- `~/.devpulse/state.db`: SQLite WAL jobs, expiring redacted snapshots, review and agent session metadata, redacted conversation turns/results, exact cache, provider circuits and an FTS5 index. Set `DEVPULSE_HOME` to choose another directory.
- `~/.devpulse/identity.key`: local HMAC key for project and cache identities; keep it with state backups.

Commit rules, memory and skills. Keep local config, state and credentials out of Git. Project memory is never automatically learned from source or old model responses. Curate it directly as it grows. FTS5 is required; startup reports an actionable error if the Python SQLite build lacks it.

The index refreshes changed/deleted memory and Git-tracked plus non-ignored untracked text files before task runs and reviews. Credential files, binaries, ignored files, generated directories and escaping paths are excluded. Indexing is bounded to 5000 paths, 20 MB total and 128 KB per document. Only redacted chunks with file/line provenance are indexed. Retrieval is local FTS5 lexical search, with up to eight memory/skill chunks and eight code chunks; it does not build a complete call graph or semantic embeddings. `memory reindex` rebuilds the derived index without editing Markdown.

The task harness refreshes the local index and retrieves relevant code and memory before each task. Its context keeps the active task and repository rules intact, then prioritizes the newest tool result and drops older observations when needed. It uses one tool call per model response to improve reliability with small local models. The serialized context budget is capped conservatively at two bytes per configured input token; displayed token counts are estimates, not provider tokenizer measurements. If required task, rules or tool data cannot fit, the run fails clearly instead of sending a prompt without that evidence. Review context planning includes mandatory source and rules first. `context --file ... --json` shows selected review provenance, estimated usage and omission reasons; `context --query "..." --json` previews retrieval without a source file.

Source intake rejects changes above 512 KB, and review output is bounded with explicit omitted-finding counts. Oversized optional index documents are skipped and reported; oversized mandatory rules are rejected.

Exact cache identity includes original source, context/index fingerprint, project, configuration, credential fingerprints and prompt/budget versions. Changed secrets cannot collide merely because both became the same placeholder. Cache TTL is 24 hours by default. A cache hit creates a session; equivalent outstanding gateway submissions share one job when caching is enabled. `--no-cache` disables both response reuse and job coalescing.

## Durable jobs

```sh
devpulse review --detach --json
devpulse jobs list --json
devpulse jobs show JOB_ID
devpulse jobs wait JOB_ID --json
devpulse jobs cancel JOB_ID
devpulse jobs retry JOB_ID
```

AI reviews submit to a persistent FIFO queue and wait by default. `--detach` returns the job ID after SQLite commits the redacted snapshot. Offline and `--direct` reviews remain synchronous and reject `--detach`. Interrupting a blocking CLI wait leaves the job recorded and prints the ID for reconnection.

One worker processes at most 100 outstanding jobs. Jobs move through `queued`, `running`, `succeeded`, `failed`, `cancelled` or `expired`; inspection shows attempts, owner/heartbeat, timestamps and terminal results. The worker heartbeats every five seconds. Restart recovery fences old worker ownership and requeues abandoned jobs within the three-attempt limit. It uses the original snapshot even if source files changed or disappeared.

Snapshots expire 24 hours after initial submission; expiry removes replay payloads. Manual retry creates a new job from an unexpired failed/cancelled snapshot and preserves its original expiry. Queued cancellation is immediate; an active network request finishes or times out before its result is discarded. There is no hard HTTP interruption. Graceful shutdown stops new execution, drains the active attempt and leaves queued jobs for restart.

Recovery is at least once at the provider boundary: a crash after a provider accepted a request can cause another billed request. The tool executes no code or patches, and cannot provide exactly-once remote inference. Job result/history metadata remains inspectable separately from expiring snapshots.

## Gateway and terminal session

```sh
devpulse gateway start
devpulse gateway status
devpulse tui
devpulse gateway stop
```

AI review starts the gateway automatically. Offline review stays in-process and makes no inference/network request. `devpulse tui` opens the same task-first terminal session as launching `devpulse` with no arguments.

One gateway owns the local state directory and listens only on `127.0.0.1` with a random bearer token. Eight HTTP handlers are allowed, with at most four compatibility `/review` waits so inspection/cancellation/health retain capacity. The CLI uses nonblocking job submission plus polling. Attempt sessions from dead processes become `interrupted`; active direct reviews remain running, while durable jobs are recovered independently. `gateway run` runs in the foreground for diagnostics. No service is installed at OS startup.

## Hardware Profiler and Model Sizing

DevPulse reads system RAM, available VRAM, and GPU architecture via OS-native telemetry (Windows, Linux, macOS), rates popular and installed Ollama coding models, predicts tokens/second (TPS), and scores Coding IQ:

```sh
devpulse models
devpulse models --json
devpulse models --base-url http://127.0.0.1:11434
```

Models are classified into three safety tiers:
- `VRAM FIT`: 100% GPU offload with maximum speed (30–60+ t/s).
- `RAM FIT`: Fits in system RAM for CPU or hybrid offload (8–15 t/s).
- `OOM DANGER`: Exceeds safe host memory thresholds; warns against Out-Of-Memory system freezes.

## Compiler-as-a-Judge and Approval Gate

Deterministic AST syntax checking and secret verification with standard exit codes:

```sh
devpulse verify --file your_code.py
devpulse verify --code "def foo(): return 42"
git diff | devpulse verify
```

- Exit code `0`: Clean (no syntax errors or secret leaks).
- Exit code `2`: Gate blocked (syntax error or secret detected). This exit code 2 standard integrates directly with Claude Code and agent pre-tool hooks.

## Multi-Agent Ecosystem Bridge and MCP Server

DevPulse integrates natively as a co-processor with **Claude Code**, **Google Antigravity**, and **OpenAI Codex CLI**:

```sh
# Configure all agents at once
devpulse integrate --all

# Or target specific agents
devpulse integrate --claude
devpulse integrate --antigravity
devpulse integrate --codex

# Synchronize .devpulse/RULES.md to CLAUDE.md and AGENTS.md
devpulse rules sync
```

Running the MCP Server directly:

```sh
devpulse mcp
```

DevPulse's MCP server exposes standard tools:
- `devpulse_review`: Full code review and security auditing with secret scrubbing.
- `devpulse_verify`: Deterministic AST syntax verification gate.
- `devpulse_search_memory`: Search project rules, conventions, and codebase knowledge.
- `devpulse_hardware_profile`: Read hardware telemetry and model sizing recommendations.
- Resources: `devpulse://rules`, `devpulse://memory`.

## Privacy and limits

Known key formats, credential assignments, bearer tokens, private keys and high-entropy strings are redacted locally before inference. Runtime provider keys are protected explicitly in reviews, memory commands and previews. Persisted data includes redacted prompts/snapshots, derived chunks, results and opaque identities. Raw source, credential values and secret-to-placeholder maps are not intentionally persisted. Provider error bodies are discarded, redirects are rejected, and remote providers require HTTPS. Human output strips terminal escape sequences.

Redaction is best effort and may miss secrets or mask ordinary values. This MVP cannot guarantee zero retention: Python strings, process memory, swap and provider retention policies are outside its control. A provider still receives redacted code. Local state is not encrypted; use a private user account/state directory, particularly on Windows where filesystem ACLs are inherited. Prompt injection is treated as untrusted input; validated model actions can write files or run commands only through project-scoped tools and the configured human approval policy.

Existing state is upgraded to schema version 5 with a consistent SQLite backup before schema changes. Backups live under the state directory's `backups/`; retain them with `identity.key`. Snapshot expiry is logical database removal, not forensic erasure from WAL, filesystem snapshots or backups. Manage backup retention separately.

This release provides a bounded task agent and local lexical code retrieval. It does not provide GitHub PR/CI automation, embeddings/vector similarity, streaming token rendering, native Anthropic/Gemini agent adapters, subagents or Codex-level capability guarantees. Small models can still make reasoning or tool-format errors; use focused tasks and verify resulting changes. Syntax validity does not establish semantic correctness.

## Development

```sh
python -m unittest discover -v
uv build
```

See [architecture](docs/architecture.md) for dependency rules and extension points. Tests use real SQLite, Git, HTTP fixtures and CLI subprocesses; a process-kill test verifies replay after gateway death and source modification. Windows is verified locally; the CI matrix includes Linux. Live cloud/Ollama behavior requires an available account or server and is separate from fixture-based validation.
