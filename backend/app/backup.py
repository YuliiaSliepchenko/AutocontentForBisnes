"""Consistent SQLite backup plus byte-for-byte asset inventory. Server must be stopped."""
import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def inventory(directory):
    root = Path(directory)
    return {str(p.relative_to(root)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and p.suffix not in {'.db', '.tmp'}
            and not p.name.endswith(('-wal', '-shm'))}


def backup(data_dir, destination):
    source, destination = Path(data_dir).resolve(), Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    counts = {}
    database = source / 'autocontent.db'
    if database.exists():
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(destination / 'autocontent.db')) as dst:
                src.backup(dst)
                assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                for (table,) in dst.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                    safe = table.replace('"', '""')
                    counts[table] = dst.execute(f'SELECT count(*) FROM "{safe}"').fetchone()[0]
    for item in source.iterdir():
        if item.name.startswith('autocontent.db'):
            continue
        if item.is_dir():
            shutil.copytree(item, destination / item.name)
        else:
            shutil.copy2(item, destination / item.name)
    manifest = {'created_at': datetime.now(timezone.utc).isoformat(), 'source': str(source),
                'row_counts': counts, 'files': inventory(source)}
    assert inventory(destination) == manifest['files']
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('data_dir')
    parser.add_argument('destination')
    args = parser.parse_args()
    print(json.dumps(backup(args.data_dir, args.destination), indent=2))
