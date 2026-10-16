"""Agent integration adapters for Claude Code, Google Antigravity, and OpenAI Codex CLI."""

import json
from pathlib import Path


def sync_rules(root: Path) -> list[str]:
    rules_path = root / ".devpulse/RULES.md"
    if not rules_path.is_file():
        return []

    content = rules_path.read_text(encoding="utf-8", errors="replace")
    header = (
        "<!-- Synced by DevPulse AI from .devpulse/RULES.md. Do not edit directly. -->\n\n"
    )
    managed = header + content

    targets = [
        root / "CLAUDE.md",
        root / "AGENTS.md",
        root / ".agents/rules/devpulse.md",
    ]

    synced = []
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(managed, encoding="utf-8")
        synced.append(str(target))

    return synced


def integrate_antigravity(root: Path) -> list[str]:
    agents_dir = root / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    config_path = agents_dir / "mcp_config.json"
    data = {}
    if config_path.is_file():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    if "mcpServers" not in data:
        data["mcpServers"] = {}

    data["mcpServers"]["devpulse"] = {
        "command": "devpulse",
        "args": ["mcp"],
    }

    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    synced = sync_rules(root)
    return [str(config_path)] + synced


def integrate_claude(root: Path) -> list[str]:
    claude_dir = root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    config_path = claude_dir / "mcp.json"
    data = {
        "mcpServers": {
            "devpulse": {
                "command": "devpulse",
                "args": ["mcp"],
            }
        }
    }
    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    # Install PreToolUse blocker hook
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    hook_bat = hooks_dir / "pre-tool-use.bat"
    hook_bat.write_text(
        "@echo off\n"
        "rem DevPulse Compiler-as-a-Judge PreToolUse hook\n"
        "rem Enforces exit code 2 on syntax failure or secret leak\n"
        "devpulse verify %*\n"
        "if errorlevel 2 exit /b 2\n"
        "exit /b 0\n",
        encoding="utf-8",
    )

    hook_sh = hooks_dir / "pre-tool-use.sh"
    hook_sh.write_text(
        "#!/usr/bin/env bash\n"
        "# DevPulse Compiler-as-a-Judge PreToolUse hook\n"
        "# Enforces exit code 2 on syntax failure or secret leak\n"
        "devpulse verify \"$@\"\n"
        "EXIT_CODE=$?\n"
        "if [ $EXIT_CODE -eq 2 ]; then\n"
        "  exit 2\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )

    synced = sync_rules(root)
    return [str(config_path), str(hook_bat), str(hook_sh)] + synced


def integrate_codex(root: Path) -> list[str]:
    codex_dir = root / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)

    config_path = codex_dir / "config.toml"
    existing = ""
    if config_path.is_file():
        existing = config_path.read_text(encoding="utf-8")

    section = '[mcp.devpulse]\ncommand = "devpulse"\nargs = ["mcp"]\n'
    if "[mcp.devpulse]" not in existing:
        updated = existing + ("\n" if existing and not existing.endswith("\n") else "") + section
        config_path.write_text(updated, encoding="utf-8")

    synced = sync_rules(root)
    return [str(config_path)] + synced


def integrate_all(root: Path) -> list[str]:
    out = []
    out.extend(integrate_antigravity(root))
    out.extend(integrate_claude(root))
    out.extend(integrate_codex(root))
    # Deduplicate while preserving order
    seen = set()
    result = []
    for item in out:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
