"""Durable project-specific consent for indexing folders without Git."""

from ..domain.indexing import IndexDecision
from .project_inspection import inspect_project


class SQLiteIndexAccess:
    def __init__(self, state):
        self.state = state

    def decision(self, root):
        inspection = inspect_project(root)
        if not inspection.complete:
            return IndexDecision(
                'unavailable',
                'Project detection was incomplete; indexing skipped.',
                inspection.is_git,
            )
        if not inspection.has_coding_files:
            return IndexDecision(
                'not_coding',
                'Not a coding repository: no programming files, Markdown documentation or project manifests found. Indexing skipped.',
                inspection.is_git,
            )
        project = self.state.identity(str(root.resolve(strict=True)))
        with self.state.connect() as db:
            row = db.execute(
                'SELECT allowed FROM index_permissions WHERE project=?', (project,)
            ).fetchone()
        if row and not row['allowed']:
            return IndexDecision(
                'declined',
                'Local project indexing was declined for this folder.',
                inspection.is_git,
            )
        if inspection.is_git or row:
            return IndexDecision('allowed', '', inspection.is_git)
        return IndexDecision(
            'needs_approval',
            'This coding folder is not a Git repository. Local indexing needs your approval; run devpulse memory reindex --approve-non-git or use an interactive session.',
            False,
        )

    def set_allowed(self, root, allowed: bool):
        if type(allowed) is not bool:
            raise ValueError('Index approval must be a boolean.')
        project = self.state.identity(str(root.resolve(strict=True)))
        with self.state.connect() as db:
            db.execute(
                'INSERT OR REPLACE INTO index_permissions(project,allowed) VALUES(?,?)',
                (project, int(allowed)),
            )
            if not allowed:
                db.execute('DELETE FROM documents WHERE project=?', (project,))
                db.execute('DELETE FROM chunks WHERE project=?', (project,))
