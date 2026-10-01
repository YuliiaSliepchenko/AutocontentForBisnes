"""Explicit, additive v1→v2 migration; trial-copy verification precedes live apply."""
import argparse
import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

VERSION = 2
ADDITIONS = [
    '''CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,
       project_id TEXT NOT NULL, from_state TEXT, to_state TEXT NOT NULL,
       action TEXT NOT NULL, revision INTEGER NOT NULL,
       created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS logos(id TEXT PRIMARY KEY, filename TEXT NOT NULL,
       colors TEXT NOT NULL, mime TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS generation_tasks(job_id TEXT PRIMARY KEY,
       payload TEXT NOT NULL, owner TEXT, lease_until REAL NOT NULL DEFAULT 0)''',
    '''CREATE TABLE IF NOT EXISTS migration_history(version INTEGER PRIMARY KEY,
       applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''',
]


def apply(database):
    with closing(sqlite3.connect(database)) as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version == VERSION:
            return
        if version not in (0, 1):
            raise RuntimeError(f'Unsupported database version: {version}')
        db.execute('BEGIN IMMEDIATE')
        try:
            for statement in ADDITIONS:
                db.execute(statement)
            for project_id, raw in db.execute('SELECT id,data FROM projects').fetchall():
                p = json.loads(raw)
                old_state = p['state']
                p['legacy_imported'] = True
                if old_state == 'COVERS_PENDING':
                    job_id = uuid4().hex
                    p.update(state='COVER_GENERATION', active_job_id=job_id)
                    request_id = f'migration-covers-{project_id}'
                    db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)',
                               (job_id, request_id, project_id, 'covers', 'queued', None))
                    db.execute('INSERT INTO generation_tasks(job_id,payload) VALUES(?,?)',
                               (job_id, json.dumps({'kind':'covers','project_id':project_id})))
                db.execute('UPDATE projects SET data=? WHERE id=?', (json.dumps(p, ensure_ascii=False), project_id))
                db.execute('INSERT INTO events(project_id,from_state,to_state,action,revision) VALUES(?,?,?,?,?)',
                           (project_id, old_state, p['state'], 'migration_v2', p['revision']))
            db.execute('INSERT INTO migration_history(version) VALUES(?)', (VERSION,))
            db.execute(f'PRAGMA user_version={VERSION}')
            db.commit()
        except BaseException:
            db.rollback()
            raise


def preserved_rows(database):
    with closing(sqlite3.connect(database)) as db:
        return {table: sorted([tuple(row) for row in db.execute(f'SELECT * FROM {table}')], key=repr)
                for table in ('brands', 'projects', 'scripts', 'slides', 'operations', 'jobs')}


def verify(before, database):
    after = preserved_rows(database)
    for table in ('brands', 'scripts', 'slides', 'operations', 'jobs'):
        assert set(before[table]).issubset(set(after[table])), table
    projects_after = {row[0]: row for row in after['projects']}
    for row in before['projects']:
        key = row[0]
        old = json.loads(row[1])
        new = json.loads(projects_after[key][1])
        assert all(new[k] == value for k, value in old.items() if k != 'state'), key
        assert new['state'] == ('COVER_GENERATION' if old['state'] == 'COVERS_PENDING' else old['state'])
    with closing(sqlite3.connect(database)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('PRAGMA user_version').fetchone()[0] == VERSION


def fingerprint(data_dir):
    from .backup import inventory
    database = Path(data_dir) / 'autocontent.db'
    return {'rows': hashlib.sha256(repr(preserved_rows(database)).encode()).hexdigest(),
            'files': inventory(data_dir)}


def trial(data_dir, backup_dir, trial_dir):
    trial_dir = Path(trial_dir)
    shutil.copytree(backup_dir, trial_dir)
    before = preserved_rows(trial_dir / 'autocontent.db')
    assert preserved_rows(Path(data_dir) / 'autocontent.db') == before, 'Backup is stale'
    apply(trial_dir / 'autocontent.db')
    verify(before, trial_dir / 'autocontent.db')
    from .backup import inventory
    source_files = inventory(data_dir)
    for filename, digest in source_files.items():
        assert inventory(trial_dir)[filename] == digest
    report = {'verified': True, 'version': VERSION, 'source': str(Path(data_dir).resolve()),
              'source_fingerprint': fingerprint(data_dir)}
    (trial_dir / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['trial', 'apply'])
    parser.add_argument('--data', default='data')
    parser.add_argument('--backup', default='backups/pre-workflow-v2')
    parser.add_argument('--trial', default='backups/trial-workflow-v2')
    args = parser.parse_args()
    if args.mode == 'trial':
        print(json.dumps(trial(args.data, args.backup, args.trial), indent=2))
    else:
        report = json.loads((Path(args.trial) / 'verification.json').read_text(encoding='utf-8'))
        if report.get('verified') is not True or report['source'] != str(Path(args.data).resolve()):
            raise RuntimeError('Verified trial required')
        if report['source_fingerprint'] != fingerprint(args.data):
            raise RuntimeError('Source changed since trial; create a new backup/trial')
        before = preserved_rows(Path(args.data) / 'autocontent.db')
        apply(Path(args.data) / 'autocontent.db')
        verify(before, Path(args.data) / 'autocontent.db')
        print('Migration applied and verified; existing rows and files preserved.')
