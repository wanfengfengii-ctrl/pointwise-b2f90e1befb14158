import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path


def is_unavailable(error):
    return getattr(error, 'sqlite_errorcode', 0) & 255 in {
        sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_CANTOPEN,
        sqlite3.SQLITE_IOERR, sqlite3.SQLITE_READONLY, sqlite3.SQLITE_FULL,
    }


class PoolStore:
    def __init__(self, path, name):
        self.path = Path(path).resolve()
        self.name = name
        self.on_commit = None

    @contextmanager
    def open(self, *, create=False):
        mode = 'rwc' if create else 'rw'
        uri = f'{self.path.as_uri()}?mode={mode}'
        with closing(sqlite3.connect(uri, uri=True)) as db:
            db.execute('PRAGMA foreign_keys = ON')
            yield db

    def initialize(self):
        with self.open(create=True) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS capacity (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    slots TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS quotas (
                    room TEXT PRIMARY KEY NOT NULL,
                    slots TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS delivery_history (
                    room TEXT NOT NULL,
                    switch_id TEXT NOT NULL,
                    step_id INTEGER NOT NULL,
                    slots TEXT NOT NULL,
                    PRIMARY KEY (room, switch_id, step_id)
                );
            ''')

    @contextmanager
    def write_transaction(self):
        with self.open() as db:
            db.execute('BEGIN IMMEDIATE')
            with db:
                yield db
            changed = db.total_changes > 0
        if changed and self.on_commit is not None:
            self.on_commit(self.name)
