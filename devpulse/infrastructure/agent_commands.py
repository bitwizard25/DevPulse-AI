"""Foreground command execution with explicit policy and bounded, scrubbed output."""

import os
import signal
import subprocess
import tempfile
import time

from .agent_process import WindowsProcessJob

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
            {'creationflags': subprocess.CREATE_NO_WINDOW | 0x00000004}
            if os.name == 'nt'
            else {'start_new_session': True}
        )
        process = None
        process_job = None
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
                if os.name == 'nt':
                    process_job = WindowsProcessJob(process)
                    # Start suspended, attach the kill-on-close job, then resume the
                    # primary thread so it cannot spawn before containment is active.
                    import ctypes
                    from ctypes import wintypes

                    class ThreadEntry(ctypes.Structure):
                        _fields_ = [
                            ('size', wintypes.DWORD),
                            ('usage', wintypes.DWORD),
                            ('thread_id', wintypes.DWORD),
                            ('owner_pid', wintypes.DWORD),
                            ('base_priority', wintypes.LONG),
                            ('delta_priority', wintypes.LONG),
                            ('flags', wintypes.DWORD),
                        ]

                    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
                    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
                    kernel.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
                    kernel.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
                    kernel.OpenThread.restype = wintypes.HANDLE
                    kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
                    kernel.ResumeThread.restype = wintypes.DWORD
                    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                    snapshot = kernel.CreateToolhelp32Snapshot(0x4, 0)
                    if snapshot == wintypes.HANDLE(-1).value:
                        raise ctypes.WinError(ctypes.get_last_error())
                    entry = ThreadEntry()
                    entry.size = ctypes.sizeof(entry)
                    try:
                        found = kernel.Thread32First(snapshot, ctypes.byref(entry))
                        while found:
                            if entry.owner_pid == process.pid:
                                thread_handle = kernel.OpenThread(0x2, False, entry.thread_id)
                                if not thread_handle:
                                    raise ctypes.WinError(ctypes.get_last_error())
                                try:
                                    if kernel.ResumeThread(thread_handle) == 0xFFFFFFFF:
                                        raise ctypes.WinError(ctypes.get_last_error())
                                finally:
                                    kernel.CloseHandle(thread_handle)
                                break
                            found = kernel.Thread32Next(snapshot, ctypes.byref(entry))
                        else:
                            raise OSError('Could not find the contained command process thread.')
                    finally:
                        kernel.CloseHandle(snapshot)
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
                if process:
                    stop_command(process)
                if process_job:
                    process_job.close()
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
