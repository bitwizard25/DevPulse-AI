"""Derived FTS5 index. All content is scrubbed before chunking or persistence."""

import hashlib
import re
import subprocess
from pathlib import Path

from ..domain.indexing import is_indexable_path
from ..domain.memory import IndexReport, MemoryChunk
from ..domain.privacy import Vault
from .agent_workspace import AgentWorkspace
from .context import relative_to_root, safe_path
from .index_access import SQLiteIndexAccess
from .source import git
from .state import State

INDEX_VERSION = 'fts-v1'
EXCLUDED_DIRS = frozenset(
    {
        '.git',
        '.devpulse',
        '.venv',
        'venv',
        'node_modules',
        'dist',
        'build',
        'generated',
        '__pycache__',
        '.next',
        '.uv-cache',
        'vendor',
        'coverage',
    }
)
EXCLUDED_SUFFIXES = frozenset(
    {
        '.pem',
        '.key',
        '.p12',
        '.pfx',
        '.crt',
        '.db',
        '.sqlite',
        '.sqlite3',
        '.lock',
        '.svg',
        '.min.js',
        '.map',
    }
)
STOP_WORDS = frozenset(
    {
        'def',
        'class',
        'return',
        'import',
        'from',
        'self',
        'none',
        'true',
        'false',
        'diff',
        'git',
        'index',
        'file',
        'print',
        'the',
        'and',
        'for',
        'with',
        'this',
    }
)


def query_terms(query: str) -> list[str]:
    terms = re.findall(r'[A-Za-z_][A-Za-z0-9_]{2,63}', query.lower())
    return list(dict.fromkeys(term for term in terms if term not in STOP_WORDS))[:24]


def chunks(path: str, kind: str, text: str) -> list[MemoryChunk]:
    result, current = [], []
    start, size = 1, 0
    for number, line in enumerate(text.splitlines(), 1):
        # Split very long lines without crossing a secret boundary (input is already redacted).
        pieces = [line[i : i + 300] for i in range(0, len(line), 300)] or ['']
        for piece in pieces:
            if current and (size + len(piece.encode()) > 1200 or number - start >= 80):
                result.append(
                    MemoryChunk(
                        path,
                        kind,
                        start,
                        number - 1 if number > start else number,
                        '\n'.join(current),
                    )
                )
                current, size, start = [], 0, number
            if not current:
                start = number
            current.append(piece)
            size += len(piece.encode()) + 1
    if current:
        result.append(
            MemoryChunk(path, kind, start, max(start, len(text.splitlines())), '\n'.join(current))
        )
    return result


class SQLiteMemoryIndex:
    def __init__(self, state: State):
        self.state = state

    def rebuild(self, root: Path, vault: Vault) -> IndexReport:
        decision = SQLiteIndexAccess(self.state).decision(root)
        if decision.status != 'allowed':
            return IndexReport(status=decision.status, skipped=[decision.reason])
        project = self.state.identity(str(root.resolve(strict=True)))
        with self.state.connect() as db:
            db.execute('DELETE FROM documents WHERE project=?', (project,))
            db.execute('DELETE FROM chunks WHERE project=?', (project,))
        return self.refresh(root, vault)

    def refresh(self, root: Path, vault: Vault) -> IndexReport:
        decision = SQLiteIndexAccess(self.state).decision(root)
        if decision.status != 'allowed':
            return IndexReport(status=decision.status, skipped=[decision.reason])
        vault = vault.fork()
        root = root.resolve(strict=True)
        project = self.state.identity(str(root))
        report = IndexReport()
        candidates = self._candidates(root, report, is_git=decision.is_git)
        documents = []
        total = 0
        for path, kind in candidates:
            try:
                path = safe_path(root, path)
                with path.open('rb') as handle:
                    raw = handle.read(128001)
                if len(raw) > 128000 or b'\0' in raw:
                    raise ValueError('binary or larger than 128 KB')
                total += len(raw)
                if total > 20 * 1024 * 1024:
                    report.skipped.append(
                        'Remaining code omitted: 20 MB project indexing limit reached.'
                    )
                    break
                name = vault.scrub(relative_to_root(root, path).as_posix())
                content = vault.scrub(raw.decode('utf-8', errors='strict'))
                documents.append((name, kind, self.state.identity(raw.hex()), content))
            except (OSError, ValueError, UnicodeError):
                report.skipped.append(
                    vault.scrub(f'{path.name}: unavailable, unsafe, binary or oversized.')
                )
        # Newly discovered values may also occur in earlier documents without a key name.
        documents = [
            (vault.scrub(name), kind, digest, vault.scrub(text))
            for name, kind, digest, text in documents
        ]
        report.skipped = [vault.scrub(item) for item in report.skipped]
        fingerprint = hashlib.sha256(INDEX_VERSION.encode())
        with self.state.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = {
                row['path']: row['fingerprint']
                for row in db.execute(
                    'SELECT path,fingerprint FROM documents WHERE project=?', (project,)
                )
            }
            names = {item[0] for item in documents}
            for deleted in existing.keys() - names:
                db.execute('DELETE FROM documents WHERE project=? AND path=?', (project, deleted))
                db.execute('DELETE FROM chunks WHERE project=? AND path=?', (project, deleted))
            for name, kind, digest, content in documents:
                # Include rendered text so vault placeholder changes also invalidate derived chunks.
                rendered = self.state.identity(digest + content)
                fingerprint.update((name + rendered).encode())
                if existing.get(name) == rendered:
                    continue
                db.execute('DELETE FROM chunks WHERE project=? AND path=?', (project, name))
                db.execute(
                    'INSERT OR REPLACE INTO documents VALUES(?,?,?,?)',
                    (project, name, rendered, kind),
                )
                for chunk in chunks(name, kind, content):
                    db.execute(
                        'INSERT INTO chunks(project,path,kind,start,end,text) VALUES(?,?,?,?,?,?)',
                        (project, chunk.path, chunk.kind, chunk.start, chunk.end, chunk.text),
                    )
            report.documents = len(documents)
            report.chunks = db.execute(
                'SELECT COUNT(*) FROM chunks WHERE project=?', (project,)
            ).fetchone()[0]
        report.fingerprint = fingerprint.hexdigest()
        return report

    def _candidates(
        self, root: Path, report: IndexReport, *, is_git: bool
    ) -> list[tuple[Path, str]]:
        base = safe_path(root, root / '.devpulse')
        memory = base / 'MEMORY.md'
        candidates = [(memory, 'memory')] if memory.is_file() else []
        skills = safe_path(root, base / 'skills')
        if skills.is_dir():
            skill_files = sorted(skills.glob('*/SKILL.md'))
            candidates.extend((path, 'memory') for path in skill_files[:20])
            if len(skill_files) > 20:
                report.skipped.append('Skills after the first 20 paths were omitted.')
        if is_git:
            try:
                names = sorted(
                    filter(
                        None,
                        git(
                            root,
                            'ls-files',
                            '--cached',
                            '--others',
                            '--exclude-standard',
                            '-z',
                            '--',
                        ).split(b'\0'),
                    )
                )
            except (ValueError, OSError, subprocess.SubprocessError):
                report.skipped.append('Code retrieval unavailable: no readable Git file list.')
                return candidates
        else:
            names = [
                relative.as_posix().encode('utf-8') for relative, _ in AgentWorkspace(root).files()
            ]
        workspace = AgentWorkspace(root)
        for raw in names[:5000]:
            name = raw.decode('utf-8', errors='replace')
            path = Path(name)
            lower_parts = {part.lower() for part in path.parts}
            filename = path.name.lower()
            if (
                lower_parts & EXCLUDED_DIRS
                or not is_indexable_path(name)
                or filename.startswith('.env')
                or filename in ('credentials', 'secrets.json', 'package-lock.json')
                or path.suffix.lower() in EXCLUDED_SUFFIXES
            ):
                report.skipped.append(f'{name}: excluded from code retrieval.')
                continue
            try:
                candidates.append((workspace.path(name), 'code'))
            except (OSError, ValueError):
                report.skipped.append(f'{name}: excluded from code retrieval.')
        if len(names) > 5000:
            report.skipped.append(
                f'{len(names) - 5000} tracked or untracked paths omitted by the 5000-file limit.'
            )
        return candidates

    def search(
        self, project: str, query: str, *, kind: str | None = None, limit: int = 8
    ) -> list[MemoryChunk]:
        if not 1 <= limit <= 50:
            raise ValueError('Search limit must be between 1 and 50.')
        terms = query_terms(query)
        if not terms:
            return []
        match = ' OR '.join('"' + term + '"' for term in terms)
        condition = ' AND kind=?' if kind else ''
        args = (project, match, kind, limit) if kind else (project, match, limit)
        with self.state.connect() as db:
            rows = db.execute(
                'SELECT path,kind,start,end,text FROM chunks WHERE project=? AND chunks MATCH ?'
                + condition
                + ' ORDER BY bm25(chunks,0,3,0,0,0,1),path,CAST(start AS INTEGER),rowid LIMIT ?',
                args,
            )
            return [
                MemoryChunk(
                    row['path'], row['kind'], int(row['start']), int(row['end']), row['text']
                )
                for row in rows
            ]

    def first_memory(self, project: str, limit: int = 8) -> list[MemoryChunk]:
        with self.state.connect() as db:
            rows = db.execute(
                "SELECT path,kind,start,end,text FROM chunks WHERE project=? AND kind='memory' ORDER BY path,CAST(start AS INTEGER),rowid LIMIT ?",
                (project, limit),
            )
            return [
                MemoryChunk(
                    row['path'], row['kind'], int(row['start']), int(row['end']), row['text']
                )
                for row in rows
            ]
