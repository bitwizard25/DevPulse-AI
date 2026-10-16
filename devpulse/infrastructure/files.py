"""Atomic local writes and cross-platform process ownership."""

import os
import time
import uuid
from pathlib import Path


def atomic_write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ProcessLock:
    def __init__(self, path: Path, timeout: float = 0):
        self.path = path
        self.timeout = timeout
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.handle = self.path.open('a+b')
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b'0')
            self.handle.flush()
        self.handle.seek(0)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt

                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    self.handle.close()
                    self.handle = None
                    raise ValueError(
                        'Another process owns this resource. Try again after it finishes.'
                    ) from None
                time.sleep(0.025)
        return self

    def __exit__(self, *args):
        if self.handle is not None:
            self.handle.seek(0)
            if os.name == 'nt':
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle, fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None
