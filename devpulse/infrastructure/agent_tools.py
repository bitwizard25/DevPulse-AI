"""Dispatch validated coding tools to focused filesystem and process adapters."""

from ..domain.agent_tools import TOOL_SPECS, validate_arguments
from ..domain.checks import check_python, finding
from .agent_commands import AgentCommands
from .agent_files import AgentFiles
from .agent_workspace import AgentWorkspace


class ProjectTools:
    def __init__(self, root, approve, vault):
        self.workspace = AgentWorkspace(root)
        self.vault = vault
        self.files = AgentFiles(self.workspace, approve, vault)
        self.commands = AgentCommands(self.workspace.root, approve, vault)

    @property
    def approve(self):
        return self.files.approve

    @approve.setter
    def approve(self, value):
        self.files.approve = self.commands.approve = value

    @staticmethod
    def describe():
        return TOOL_SPECS

    def execute(self, name, arguments):
        validate_arguments(name, arguments)
        handlers = {
            'list_files': self.list_files,
            'search_text': self.search_text,
            'read_file': self.files.read_file,
            'write_file': self.files.write_file,
            'edit_file': self.files.edit_file,
            'run_command': self.commands.run_command,
            'verify_file': self.verify_file,
        }
        return handlers[name](arguments)

    def list_files(self, args):
        query = args.get('query', '').casefold()
        paths = []
        for relative, _ in self.workspace.files():
            if query in relative.as_posix().casefold():
                paths.append(relative.as_posix())
                if len(paths) >= 300:
                    break
        return {'paths': paths, 'truncated': len(paths) >= 300}

    def search_text(self, args):
        query = args['query']
        if not query.strip() or len(query) > 200:
            raise ValueError('Search query must contain 1 to 200 characters.')
        matches, total = [], 0
        for relative, path in self.workspace.files():
            try:
                raw = self.workspace.read(path)
            except (ValueError, OSError):
                continue
            total += len(raw)
            if total > 20 * 1024 * 1024:
                return {'matches': matches, 'truncated': True}
            text = self.vault.scrub(raw.decode('utf-8'))
            for number, line in enumerate(text.splitlines(), 1):
                if query.casefold() in line.casefold():
                    matches.append(
                        {'path': relative.as_posix(), 'line': number, 'text': line[:500]}
                    )
                    if len(matches) >= 40:
                        return {'matches': matches, 'truncated': True}
        return {'matches': matches, 'truncated': False}

    def verify_file(self, args):
        path = self.workspace.path(args['path'])
        content = self.workspace.read(path).decode('utf-8')
        name = path.relative_to(self.workspace.root).as_posix()
        vault = self.vault.fork()
        vault.scrub(content)
        findings = check_python([{'path': name, 'content': content}])
        if vault.count:
            findings.append(
                finding(
                    'secret-detected',
                    'warning',
                    name,
                    1,
                    f'{vault.count} potential secret value(s) detected; values were not returned.',
                )
            )
        return {'status': 'findings' if findings else 'clean', 'findings': findings}
