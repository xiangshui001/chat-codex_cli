"""Versioned, durable Issue inbox and idempotent reply outbox."""
import json
from .mvp0_runner import utc_now

REMOTE_SQL="""
CREATE TABLE IF NOT EXISTS remote_channels (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id), activated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS remote_messages (
    id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), comment_id INTEGER NOT NULL,
    action TEXT NOT NULL, text TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', received_at TEXT NOT NULL,
    UNIQUE(task_id,comment_id));
CREATE TABLE IF NOT EXISTS remote_replies (
    id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), reply_key TEXT NOT NULL UNIQUE,
    body TEXT NOT NULL, comment_id INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS remote_runs (
    id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), generation INTEGER NOT NULL,
    reason TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(task_id,generation));
CREATE INDEX IF NOT EXISTS remote_inbox ON remote_messages(task_id,state,comment_id);
CREATE INDEX IF NOT EXISTS remote_outbox ON remote_replies(comment_id,id);
"""


class RemoteStore:
    def queue_reply(self,task_id,key,body):
        # GitHub has a comment-length limit; split replies rather than reject a long answer.
        if len(body)>60000:
            for offset in range(0,len(body),60000):self.queue_reply(task_id,key+'/'+str(offset),body[offset:offset+60000])
            return
        self.db.execute('INSERT OR IGNORE INTO remote_replies(task_id,reply_key,body,created_at) VALUES(?,?,?,?)',
                        (task_id,key,body,utc_now()))

    def inbox(self,task_id):
        return [dict(r) for r in self.db.execute("SELECT * FROM remote_messages WHERE task_id=? AND state='queued' ORDER BY comment_id",(task_id,))]

    def delivered_message(self,ident):
        with self.transaction():
            self.db.execute("UPDATE remote_messages SET state='delivered' WHERE id=?",(ident,))

    def generation(self,task_id):
        row=self.db.execute('SELECT MAX(generation) FROM remote_runs WHERE task_id=?',(task_id,)).fetchone()
        return row[0] or 0

    def reopen(self,task_id,reason):
        with self.transaction():
            row,d=self.get(task_id),self.delivery(task_id)
            if row['state'] in {'queued','running'}:return False
            session=d['session_id'] or json.loads(d['options_json'])['session'].get('id')
            if session:
                for active in self.active_tasks():
                    other=self.delivery(active['id'])
                    if session in {other['session_id'],json.loads(other['options_json'])['session'].get('id')}:
                        self.queue_reply(task_id,'session-wait/'+row['request_id']+'/'+str(active['id']),
                            '已收到续跑指示。这个对话正在处理另一项任务，结束后会自动继续，避免同时覆盖上下文。')
                        return False
            generation=self.generation(task_id)+1
            self.db.execute('INSERT INTO remote_runs(task_id,generation,reason,snapshot,created_at) VALUES(?,?,?,?,?)',
                (task_id,generation,reason,json.dumps({'task':dict(row),'delivery':dict(d)}),utc_now()))
            self.db.execute("UPDATE tasks SET state='queued',started_at=NULL,finished_at=NULL,error=NULL,exit_code=NULL,diff_nonempty=NULL,summary='已收到原 Issue 的新指示，正在继续原对话。',receipt_comment_id=NULL WHERE id=?",(task_id,))
            self.db.execute("UPDATE deliveries SET execution_completed=0,publication_state='not_started' WHERE task_id=?",(task_id,))
            self.event(task_id,'remote_resumed',{'generation':generation,'reason':reason})
            return True

    def effective_paths(self,task_id):
        original=json.loads(self.get(task_id)['write_paths'])
        for r in self.db.execute("SELECT text FROM remote_messages WHERE task_id=? AND action='allow' ORDER BY id",(task_id,)):
            from .mvp0 import write_path
            for raw in r['text'].splitlines():
                raw=raw.strip()
                if raw:
                    path='.' if raw in {'.','./','*','/'} else write_path(raw,remote=True)
                    if path not in original:original.append(path)
        return tuple(original)
