import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from devpulse.application.mcp import McpServer
from devpulse.domain.hardware import HardwareProfile
from devpulse.domain.mcp import McpRequest


class McpTests(unittest.TestCase):
    def setUp(self):
        self.mock_engine = MagicMock()
        self.mock_engine.review.return_value = {
            "mode": "offline",
            "provider": "offline",
            "cache": "miss",
            "elapsed_ms": 12,
            "summary": "Clean code",
            "findings": [],
            "redacted_values": 0,
            "session": "sess-123",
            "context": {"truncated": False},
        }
        self.mock_index = MagicMock()
        self.mock_index.search.return_value = []
        self.server = McpServer(
            root=Path("."),
            engine_factory=lambda: self.mock_engine,
            memory_index_factory=lambda: self.mock_index,
            hardware_prober=lambda: HardwareProfile(
                total_ram_bytes=16 * 1024**3,
                available_ram_bytes=12 * 1024**3,
                vram_bytes=8 * 1024**3,
                gpu_name="NVIDIA RTX 4070",
                os_name="Linux",
            ),
        )

    def test_initialize_handshake(self):
        req = McpRequest(
            id=1,
            method="initialize",
            params={"protocolVersion": "2024-11-05", "clientInfo": {"name": "test-client"}},
        )
        res = self.server.handle_request(req)
        self.assertEqual(res.id, 1)
        self.assertEqual(res.result["protocolVersion"], "2024-11-05")
        self.assertIn("tools", res.result["capabilities"])

    def test_tools_list_exposes_expected_tools(self):
        req = McpRequest(id=2, method="tools/list")
        res = self.server.handle_request(req)
        tools = res.result["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("devpulse_review", tool_names)
        self.assertIn("devpulse_verify", tool_names)
        self.assertIn("devpulse_search_memory", tool_names)
        self.assertIn("devpulse_hardware_profile", tool_names)

    def test_tools_call_verify_clean_code(self):
        req = McpRequest(
            id=3,
            method="tools/call",
            params={"name": "devpulse_verify", "arguments": {"code": "def foo(): return 1\n"}},
        )
        res = self.server.handle_request(req)
        self.assertIsNone(res.error)
        content = res.result["content"]
        self.assertEqual(len(content), 1)
        data = json.loads(content[0]["text"])
        self.assertEqual(data["status"], "clean")

    def test_tools_call_verify_syntax_error(self):
        req = McpRequest(
            id=4,
            method="tools/call",
            params={"name": "devpulse_verify", "arguments": {"code": "def broken(:\n"}},
        )
        res = self.server.handle_request(req)
        self.assertIsNone(res.error)
        content = res.result["content"]
        data = json.loads(content[0]["text"])
        self.assertEqual(data["status"], "failed")
        self.assertTrue(any(e["rule"] == "python-syntax" for e in data["errors"]))

    def test_tools_call_hardware_profile(self):
        req = McpRequest(
            id=5,
            method="tools/call",
            params={"name": "devpulse_hardware_profile", "arguments": {}},
        )
        res = self.server.handle_request(req)
        self.assertIsNone(res.error)
        data = json.loads(res.result["content"][0]["text"])
        self.assertIn("hardware", data)
        self.assertEqual(data["hardware"]["gpu"], "NVIDIA RTX 4070")

    def test_resources_list(self):
        req = McpRequest(id=6, method="resources/list")
        res = self.server.handle_request(req)
        resources = res.result["resources"]
        uris = [r["uri"] for r in resources]
        self.assertIn("devpulse://rules", uris)


if __name__ == "__main__":
    unittest.main()
