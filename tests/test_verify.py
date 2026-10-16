import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="devpulse-verify-test-")
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_cli(self, *args, input_data=None):
        checkout = Path(__file__).resolve().parents[1]
        env = {
            **os.environ,
            "PYTHONPATH": str(checkout),
            "PYTHONUTF8": "1",
        }
        cmd = [
            sys.executable,
            "-m",
            "devpulse",
            "--project",
            str(self.root),
            *args,
        ]
        return subprocess.run(
            cmd,
            cwd=str(self.root),
            env=env,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_verify_clean_python_code(self):
        f = self.root / "clean.py"
        f.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
        proc = self.run_cli("verify", "--file", "clean.py")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Clean", proc.stdout)

    def test_verify_syntax_error_exits_with_code_2(self):
        f = self.root / "broken.py"
        f.write_text("def broken(:\n    pass\n", encoding="utf-8")
        proc = self.run_cli("verify", "--file", "broken.py")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("python-syntax", proc.stdout + proc.stderr)
        self.assertIn("broken.py:1", proc.stdout + proc.stderr)

    def test_verify_secret_leak_exits_with_code_2(self):
        f = self.root / "leak.py"
        f.write_text(
            'AWS_KEY = "AKIA1234567890ABCDEF"\nprint(AWS_KEY)\n',
            encoding="utf-8",
        )
        proc = self.run_cli("verify", "--file", "leak.py")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Secret detected", proc.stdout + proc.stderr)
        # Raw secret should be scrubbed in output!
        self.assertNotIn("AKIA1234567890ABCDEF", proc.stdout + proc.stderr)

    def test_verify_stdin_pipe(self):
        code = "def valid(): return 42\n"
        proc = self.run_cli("verify", input_data=code)
        self.assertEqual(proc.returncode, 0)

        broken = "def invalid( x: return\n"
        proc = self.run_cli("verify", input_data=broken)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
