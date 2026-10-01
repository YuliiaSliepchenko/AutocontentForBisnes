"""Durable leased jobs. Provider I/O never holds a SQLite write transaction."""
import json
import time
from uuid import uuid4


class JobBusy(Exception):
    pass


class JobRunner:
    def __init__(self, store, lease_seconds=30):
        self.store = store
        self.lease_seconds = lease_seconds

    def run(self, job_id, generate, complete):
        owner = uuid4().hex
        deadline = time.monotonic() + 3
        while True:
            with self.store.connect(write=True) as db:
                row = db.execute('SELECT j.status,t.payload,t.owner,t.lease_until FROM jobs j JOIN generation_tasks t ON j.id=t.job_id WHERE j.id=?', (job_id,)).fetchone()
                if row is None:
                    raise ValueError('Generation task not found')
                if row['status'] == 'succeeded':
                    return
                busy = row['owner'] and row['lease_until'] > time.time()
                if not busy:
                    db.execute('UPDATE generation_tasks SET owner=?,lease_until=? WHERE job_id=?',
                               (owner,time.time()+self.lease_seconds,job_id))
                    db.execute("UPDATE jobs SET status='running',error=NULL WHERE id=?", (job_id,))
                    payload = json.loads(row['payload'])
                    break
            if time.monotonic() >= deadline:
                raise JobBusy('Generation is already running; retry this request later')
            time.sleep(.025)
        try:
            output = generate(payload, job_id)
            with self.store.connect(write=True) as db:
                current = db.execute('SELECT owner FROM generation_tasks WHERE job_id=?', (job_id,)).fetchone()
                if current['owner'] != owner:
                    raise JobBusy('Job lease changed; result not committed')
                complete(db, payload, job_id, output)
                db.execute("UPDATE jobs SET status='succeeded',error=NULL WHERE id=?", (job_id,))
                db.execute('UPDATE generation_tasks SET owner=NULL,lease_until=0 WHERE job_id=?', (job_id,))
        except Exception as exc:
            with self.store.connect(write=True) as db:
                current = db.execute('SELECT owner FROM generation_tasks WHERE job_id=?', (job_id,)).fetchone()
                if current and current['owner'] == owner:
                    db.execute("UPDATE jobs SET status='failed',error=? WHERE id=?", (str(exc)[:500],job_id))
                    db.execute('UPDATE generation_tasks SET owner=NULL,lease_until=0 WHERE job_id=?', (job_id,))
            raise
