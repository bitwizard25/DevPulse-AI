"""Inspect file names without reading or indexing their contents."""

import os
import subprocess
from pathlib import Path

from ..domain.indexing import ProjectInspection, is_coding_path
from .agent_workspace import EXCLUDED, AgentWorkspace
from .source import git

MAX_INSPECTION_PATHS = 5000


def inspect_project(root: Path) -> ProjectInspection:
    root = root.resolve(strict=True)
    workspace = AgentWorkspace(root)
    try:
        is_git = git(root, 'rev-parse', '--is-inside-work-tree').strip() == b'true'
    except (OSError, ValueError):
        is_git = False
    except subprocess.SubprocessError:
        return ProjectInspection(False, False, complete=False)
    if is_git:
        try:
            names = git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').split(
                b'\0'
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            return ProjectInspection(True, False, complete=False)
        for raw in names[:MAX_INSPECTION_PATHS]:
            try:
                name = raw.decode('utf-8', errors='strict')
                if name and is_coding_path(name) and workspace.path(name).is_file():
                    return ProjectInspection(True, True)
            except (OSError, ValueError, UnicodeError):
                continue
        return ProjectInspection(True, False, len(names) <= MAX_INSPECTION_PATHS)
    pending, scanned = [root], 0
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    scanned += 1
                    if scanned > MAX_INSPECTION_PATHS:
                        return ProjectInspection(False, False, complete=False)
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.casefold() not in EXCLUDED:
                            pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False) and is_coding_path(entry.name):
                        try:
                            workspace.path(Path(entry.path).relative_to(root).as_posix())
                        except ValueError:
                            continue
                        return ProjectInspection(False, True)
        except OSError:
            return ProjectInspection(False, False, complete=False)
    return ProjectInspection(False, False)
