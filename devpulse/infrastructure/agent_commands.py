"""Foreground command execution with explicit policy and bounded, scrubbed output."""

import os
import signal
import subprocess
import tempfile
import time

OUTPUT_LIMIT = 1024 * 1024


def stop_command(process):
    """Stop the command tree on timeout/interruption before cleaning its output spool."""
    if os.name == 'nt':
        executable = os.path.join(
            os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'taskkill.exe'
        )
        try:
            subprocess.run(
                [executable, '/PID', str(process.pid), '/T', '/F'],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


class AgentCommands:
    def __init__(self, root, approve, vault):
        self.root, self.approve, self.vault = root, approve, vault

    def run_command(self, arguments):
        argv = arguments['argv']
        if any(not part or len(part) > 4000 or '\0' in part for part in argv):
            raise ValueError('Command arguments must be nonempty, bounded strings.')
        if not self.approve('command', subprocess.list2cmdline(argv), ''):
            return {'status': 'denied', 'argv': argv}
        env = {
            name: os.environ[name]
            for name in ('PATH', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP')
            if name in os.environ
        }
        env.update({'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', 'CI': '1'})
        timeout = arguments.get('timeout', 60)
        options = (
            {'creationflags': subprocess.CREATE_NO_WINDOW}
            if os.name == 'nt'
            else {'start_new_session': True}
        )
        process = None
        with tempfile.TemporaryFile() as output_file:
            try:
                process = subprocess.Popen(
                    argv,
                    cwd=self.root,
                    env=env,
                    shell=False,
                    stdin=subprocess.DEVNULL,
                    stdout=output_file,
                    stderr=subprocess.STDOUT,
                    **options,
                )
                deadline = time.monotonic() + timeout
                timed_out = output_limited = False
                while process.poll() is None:
                    output_file.seek(0, os.SEEK_END)
                    output_limited = output_file.tell() > OUTPUT_LIMIT
                    timed_out = time.monotonic() >= deadline
                    if output_limited or timed_out:
                        stop_command(process)
                        break
                    time.sleep(0.025)
                process.wait(timeout=5)
                output_file.seek(0)
                raw = output_file.read(OUTPUT_LIMIT + 1)
                output_limited |= len(raw) > OUTPUT_LIMIT
            finally:
                if process and process.poll() is None:
                    stop_command(process)
        text = (
            '[output limit reached; output discarded]'
            if output_limited
            else self.vault.scrub(raw.decode('utf-8', errors='replace'))
        )
        return {
            'status': 'completed',
            'exit_code': process.returncode,
            'output': text[:16000],
            'timed_out': timed_out,
            'output_limited': output_limited,
            'truncated': output_limited or len(text) > 16000,
        }
