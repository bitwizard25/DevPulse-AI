"""Persistent provider cooldowns; endpoint/configuration keys are opaque."""

from .state import State


class SQLiteCircuits:
    def __init__(self, state: State):
        self.state = state

    def read(self, key: str) -> tuple[int, float]:
        with self.state.connect() as db:
            row = db.execute(
                'SELECT failures,opened_until FROM circuits WHERE key=?',
                (self.state.identity(key),),
            ).fetchone()
        return (row['failures'], row['opened_until']) if row else (0, 0)

    def write(self, key: str, failures: int, opened_until: float):
        with self.state.connect() as db:
            db.execute(
                'INSERT OR REPLACE INTO circuits VALUES(?,?,?)',
                (self.state.identity(key), failures, opened_until),
            )
