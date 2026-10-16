"""Read bounded, consistent Git snapshots without invoking a shell."""

import subprocess
from pathlib import Path

from .context import safe_path

MAX_SOURCE = 512000


def git(root: Path, *args: str) -> bytes:
    # Spool output instead of keeping unbounded subprocess stdout in memory.
    import tempfile

    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            ['git', '-C', str(root), '--no-pager', *args],
            stdout=output,
            stderr=subprocess.PIPE,
            timeout=20,
        )
        if result.returncode:
            raise ValueError(
                'Git could not read this snapshot. Run inside a Git repository and check the index.'
            )
        output.seek(0)
        data = output.read(MAX_SOURCE + 1)
    if len(data) > MAX_SOURCE:
        raise ValueError('Source exceeds 512 KB. Review a smaller change or use --file.')
    return data


def read_file(path: Path) -> str:
    with path.open('rb') as handle:
        raw = handle.read(MAX_SOURCE + 1)
    if len(raw) > MAX_SOURCE:
        raise ValueError('File exceeds the 512 KB review limit.')
    if b'\x00' in raw:
        raise ValueError('Binary files cannot be reviewed.')
    return raw.decode('utf-8', errors='replace')


def resolve_file(root: Path, file: str) -> Path:
    target = root / file
    if target.is_file():
        return safe_path(root, target)
    filename = Path(file).name
    ignored_dirs = {'.git', '.venv', '.uv-cache', 'build', 'dist', '__pycache__', '.devpulse'}
    matches = [
        p
        for p in root.rglob(filename)
        if p.is_file()
        and not any(
            part in ignored_dirs or part.startswith('.') for part in p.relative_to(root).parts
        )
    ]
    if len(matches) == 1:
        return safe_path(root, matches[0])
    if len(matches) > 1:
        options = ', '.join(p.relative_to(root).as_posix() for p in matches[:5])
        raise ValueError(f"Ambiguous file '{file}'. Multiple matches found: {options}")
    return safe_path(root, target)


def collect(root: Path, *, file: str | None = None, worktree: bool = False) -> dict:
    root = root.resolve(strict=True)
    if file:
        path = resolve_file(root, file)
        content = read_file(path)
        name = path.relative_to(root).as_posix()
        return {
            'kind': 'file',
            'text': f'File: {name}\n{content}',
            'files': [{'path': name, 'content': content}],
        }
    top = Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve()
    if top != root:
        raise ValueError(
            'For diff reviews, use the repository root as --project so project rules and file paths agree.'
        )
    # Whole-repository diffs and file snapshots must share the same base.
    root = top
    flags = [] if worktree else ['--cached']
    diff = git(root, 'diff', *flags, '--no-ext-diff', '--no-textconv', '--unified=3', '--').decode(
        'utf-8', errors='replace'
    )
    names = list(
        filter(
            None,
            git(root, 'diff', *flags, '--name-only', '--diff-filter=ACMR', '-z', '--').split(b'\0'),
        )
    )
    if len(names) > 100:
        raise ValueError('More than 100 changed files. Split the review.')
    files = []
    size = len(diff.encode())
    for raw in names:
        name = raw.decode('utf-8', errors='strict')
        if not name.endswith('.py'):
            continue
        if worktree:
            content = read_file(safe_path(root, root / name))
        else:
            content = git(root, 'show', f':{name}').decode('utf-8', errors='replace')
        size += len(content.encode())
        if size > MAX_SOURCE:
            raise ValueError('Diff plus Python snapshots exceeds 512 KB. Split the review.')
        files.append({'path': name, 'content': content})
    return {'kind': 'worktree' if worktree else 'staged', 'text': diff, 'files': files}
