import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, directory: Path):
        self.directory = Path(directory).resolve()
        self.assets = self.directory / 'assets'
        self.assets.mkdir(parents=True, exist_ok=True)
        self.database = self.directory / 'autocontent.db'
        fresh = not self.database.exists()
        if not fresh:
            with self.connect(snapshot=False) as db:
                version = db.execute('PRAGMA user_version').fetchone()[0]
            if version != 2:
                raise RuntimeError('Database needs explicit verified migration. See docs/migration-plan.md.')
        with self.connect(snapshot=False) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS brands(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scripts(
                    project_id TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(project_id, version));
                CREATE TABLE IF NOT EXISTS slides(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, number INTEGER NOT NULL,
                    version INTEGER NOT NULL, variant TEXT NOT NULL, asset_id TEXT UNIQUE NOT NULL,
                    data TEXT NOT NULL, UNIQUE(project_id, number, variant, version));
                CREATE TABLE IF NOT EXISTS operations(
                    request_id TEXT PRIMARY KEY, signature TEXT NOT NULL, kind TEXT NOT NULL,
                    project_id TEXT, payload TEXT NOT NULL, status TEXT NOT NULL,
                    response TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    project_id TEXT, kind TEXT NOT NULL, status TEXT NOT NULL, error TEXT);
            ''')
        if fresh:
            from .migrations import apply
            apply(self.database)

    @contextmanager
    def connect(self, write=False, snapshot=True):
        db = sqlite3.connect(self.database, timeout=60)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            elif snapshot:
                db.execute('BEGIN')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()


def dump(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
