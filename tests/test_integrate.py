import json
import tempfile
import unittest
from pathlib import Path

from devpulse.infrastructure.integrate import (
    integrate_antigravity,
    integrate_claude,
    integrate_codex,
    sync_rules,
)


class IntegrateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="devpulse-integrate-test-")
        self.root = Path(self.temp_dir.name)
        (self.root / ".devpulse").mkdir()
        (self.root / ".devpulse/RULES.md").write_text(
            "# DevPulse Project Rules\n\n- Write unit tests first.\n- Zero secret leakage.\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_sync_rules_updates_claude_and_agents_md(self):
        synced = sync_rules(self.root)
        self.assertIn("CLAUDE.md", [Path(p).name for p in synced])
        self.assertIn("AGENTS.md", [Path(p).name for p in synced])

        claude_text = (self.root / "CLAUDE.md").read_text(encoding="utf-8")
        agents_text = (self.root / "AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("Synced by DevPulse AI", claude_text)
        self.assertIn("Write unit tests first", claude_text)
        self.assertIn("Synced by DevPulse AI", agents_text)
        self.assertIn("Write unit tests first", agents_text)

    def test_integrate_antigravity(self):
        files = integrate_antigravity(self.root)
        self.assertTrue(len(files) > 0)
        mcp_cfg = self.root / ".agents/mcp_config.json"
        self.assertTrue(mcp_cfg.is_file())
        data = json.loads(mcp_cfg.read_text(encoding="utf-8"))
        self.assertIn("devpulse", data["mcpServers"])
        self.assertEqual(data["mcpServers"]["devpulse"]["args"], ["mcp"])

    def test_integrate_claude(self):
        files = integrate_claude(self.root)
        self.assertTrue(len(files) > 0)
        claude_cfg = self.root / ".claude/mcp.json"
        self.assertTrue(claude_cfg.is_file())
        data = json.loads(claude_cfg.read_text(encoding="utf-8"))
        self.assertIn("devpulse", data["mcpServers"])
        # Hook scripts generated
        hook_bat = self.root / ".claude/hooks/pre-tool-use.bat"
        hook_sh = self.root / ".claude/hooks/pre-tool-use.sh"
        self.assertTrue(hook_bat.is_file())
        self.assertTrue(hook_sh.is_file())
        self.assertIn("devpulse verify", hook_bat.read_text(encoding="utf-8"))

    def test_integrate_codex(self):
        files = integrate_codex(self.root)
        self.assertTrue(len(files) > 0)
        codex_cfg = self.root / ".codex/config.toml"
        self.assertTrue(codex_cfg.is_file())
        content = codex_cfg.read_text(encoding="utf-8")
        self.assertIn("[mcp.devpulse]", content)
        self.assertIn('command = "devpulse"', content)


if __name__ == "__main__":
    unittest.main()
