import json
import sqlite3

from backend.app.backup import backup
from backend.app.migrations import apply, preserved_rows, trial, verify


def test_populated_legacy_database_preserves_history(tmp_path):
    # Build a real v1 schema without importing/starting the application.
    source = tmp_path / 'legacy'
    source.mkdir()
    database = source / 'autocontent.db'
    with sqlite3.connect(database) as db:
        for table in ('brands', 'projects', 'slides', 'operations'):
            db.execute(f'CREATE TABLE {table}(id TEXT PRIMARY KEY, data TEXT)')
        db.execute('CREATE TABLE scripts(project_id TEXT,version INTEGER,data TEXT,PRIMARY KEY(project_id,version))')
        db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,request_id TEXT UNIQUE,project_id TEXT,kind TEXT,status TEXT,error TEXT)')
        for i, state in enumerate(('SCRIPT_REVIEW', 'COVERS_PENDING', 'COVER_SELECTION', 'SLIDE_REVIEW', 'COMPLETED')):
            p = {'id':str(i),'state':state,'revision':3,'script_version':2,'current_slide':2}
            db.execute('INSERT INTO projects VALUES(?,?)', (str(i), json.dumps(p)))
        for table in ('brands', 'slides', 'operations'):
            db.execute(f'INSERT INTO {table} VALUES(?,?)', ('old', 'unchanged history'))
        for version in (1, 2, 3):
            db.execute('INSERT INTO scripts VALUES(?,?,?)', ('old', version, f'script version {version}'))
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)', ('old','old','0','render','succeeded',None))
    (source / 'assets').mkdir()
    (source / 'assets' / 'v1.png').write_bytes(b'existing-version-one')
    (source / 'assets' / 'v2.png').write_bytes(b'existing-version-two')
    before = preserved_rows(database)
    backup_dir = tmp_path / 'backup'
    backup(source, backup_dir)
    report = trial(source, backup_dir, tmp_path / 'trial')
    assert report['verified']
    assert preserved_rows(database) == before  # trial did not touch source
    apply(database)
    verify(before, database)
    after = preserved_rows(database)
    apply(database)
    assert preserved_rows(database) == after
    assert (source / 'assets' / 'v1.png').read_bytes() == b'existing-version-one'
    assert (source / 'assets' / 'v2.png').read_bytes() == b'existing-version-two'
