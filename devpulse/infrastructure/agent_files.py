"""Ranged reads and optimistic file edits that preserve untouched source bytes."""

import difflib
import hashlib
import hmac
import secrets

from .agent_guidance import scoped_guidance
from .agent_workspace import AgentWorkspace
from .context import relative_to_root
from .files import atomic_write_bytes
from .source import MAX_SOURCE


class AgentFiles:
    def __init__(self, workspace: AgentWorkspace, approve, vault):
        self.workspace, self.approve, self.vault = workspace, approve, vault
        self._key = secrets.token_bytes(32)
        self._reads: dict = {}
        self._guidance: dict[str, str] = {}

    def set_guidance(self, items):
        self._guidance = {item['path']: item['text'] for item in items}

    def _require_guidance(self, path):
        instructions = scoped_guidance(self.workspace.root, path, self.vault)
        unseen = [item for item in instructions if self._guidance.get(item['path']) != item['text']]
        if unseen:
            return {
                'status': 'instructions_required',
                'path': relative_to_root(self.workspace.root, path).as_posix(),
                'instructions': unseen,
            }
        return None

    def _fingerprint(self, raw):
        return hmac.new(self._key, raw, hashlib.sha256).hexdigest()

    def read_file(self, args):
        path = self.workspace.path(args['path'])
        raw = self.workspace.read(path)
        instructions = scoped_guidance(self.workspace.root, path, self.vault)
        # Scrub the complete document before slicing so partial secrets cannot escape.
        text = self.vault.scrub(raw.decode('utf-8')).replace('\r\n', '\n')
        lines = text.splitlines(keepends=True)
        start, limit = args.get('start_line', 1), args.get('limit', 200)
        if type(start) is not int or start < 1 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Read ranges require start_line >= 1 and limit between 1 and 1000.')
        selected, size = [], 0
        for line in lines[start - 1 : start - 1 + limit]:
            if size + len(line.encode()) > 16000:
                if not selected:
                    raise ValueError(
                        'Line exceeds the 16 KB read limit; use search_text to locate a smaller edit.'
                    )
                break
            selected.append(line)
            size += len(line.encode())
        end = start + len(selected) - 1
        truncated = start > 1 or end < len(lines)
        fingerprint = self._fingerprint(raw)
        self._reads[path] = (fingerprint, not truncated)
        return {
            'path': relative_to_root(self.workspace.root, path).as_posix(),
            'content': ''.join(selected),
            'start_line': start,
            'end_line': max(start - 1, end),
            'total_lines': len(lines),
            'truncated': truncated,
            'fingerprint': fingerprint,
            'instructions': instructions,
        }

    def _existing(self, path, args, *, full=False):
        known = self._reads.get(path)
        if not known or args.get('expected_fingerprint') != known[0]:
            raise ValueError('Read the file first and pass its expected_fingerprint.')
        if full and not known[1]:
            raise ValueError('A partial read cannot authorize full replacement; use edit_file.')
        raw = self.workspace.read(path)
        if self._fingerprint(raw) != known[0]:
            raise ValueError('File changed since it was read; read it again before editing.')
        return raw

    def write_file(self, args):
        path = self.workspace.path(args['path'])
        required = self._require_guidance(path)
        if required:
            return required
        content = args.get('content')
        self._validate_content(content)
        if path.exists():
            raw = self._existing(path, args, full=True)
            if self.vault.fork().scrub(raw.decode('utf-8')) != raw.decode('utf-8'):
                raise ValueError(
                    'Full replacement of a redacted file is unsafe; use edit_file outside secret text.'
                )
        else:
            raw = None
        return self._commit(path, raw, content.encode('utf-8'))

    def edit_file(self, args):
        path = self.workspace.path(args['path'])
        required = self._require_guidance(path)
        if required:
            return required
        raw = self._existing(path, args)
        old, new = args.get('old_text'), args.get('new_text')
        self._validate_content(new)
        if not isinstance(old, str) or not old or '__SECRET_' in old:
            raise ValueError('old_text must be nonempty source text outside redacted secrets.')
        text = raw.decode('utf-8')
        newline = '\r\n' if b'\r\n' in raw else '\n'
        old = old.replace('\r\n', '\n').replace('\n', newline)
        new = new.replace('\r\n', '\n').replace('\n', newline)
        if text.count(old) != 1:
            raise ValueError(
                'old_text must match exactly once; include more context for an ambiguous edit.'
            )
        return self._commit(path, raw, text.replace(old, new, 1).encode('utf-8'))

    @staticmethod
    def _validate_content(content):
        if not isinstance(content, str) or len(content.encode()) > MAX_SOURCE or '\0' in content:
            raise ValueError('File content must be UTF-8 text within the 512 KB tool limit.')
        if '__SECRET_' in content:
            raise ValueError('Redacted secret placeholders cannot be written to source files.')

    def _commit(self, path, before, after):
        if len(after) > MAX_SOURCE:
            raise ValueError('Edited file exceeds 512 KB.')
        name = relative_to_root(self.workspace.root, path).as_posix()
        diff = ''.join(
            difflib.unified_diff(
                (before or b'').decode('utf-8').splitlines(keepends=True),
                after.decode('utf-8').splitlines(keepends=True),
                fromfile=name,
                tofile=name,
            )
        )
        safe_diff = self.vault.scrub(diff)
        if len(safe_diff.encode()) > 24000:
            raise ValueError('Proposed diff exceeds 24 KB; split the change.')
        if before == after:
            return {'status': 'unchanged', 'path': name}
        if not self.approve('write', name, safe_diff):
            return {'status': 'denied', 'path': name}
        # Recheck both containment and file contents after the human approval boundary.
        if (
            self.workspace.path(name) != path
            or (self.workspace.read(path) if path.exists() else None) != before
        ):
            raise ValueError('File changed while approval was pending; read it again.')
        mode = path.stat().st_mode & 0o777 if before is not None else 0o644
        atomic_write_bytes(path, after, mode=mode)
        self._reads.pop(path, None)
        return {'status': 'written', 'path': name, 'diff': safe_diff}
