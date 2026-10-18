"""Foreground-only approval for indexing a coding folder outside Git."""

import sys

from ..infrastructure.index_access import SQLiteIndexAccess


def ensure_index_access(root, state, *, interactive=False, approve_non_git=False):
    access = SQLiteIndexAccess(state)
    decision = access.decision(root)
    if decision.status == 'allowed':
        return True
    if approve_non_git and decision.status in ('needs_approval', 'declined'):
        access.set_allowed(root, True)
        return True
    if decision.status == 'needs_approval' and interactive:
        print('This coding folder is not a Git repository.', file=sys.stderr)
        approved = input('Create a local code index for this folder? [y/N] ').strip().lower() in (
            'y',
            'yes',
        )
        access.set_allowed(root, approved)
        return approved
    print(decision.reason, file=sys.stderr)
    return False
