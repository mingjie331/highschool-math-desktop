"""Persist import sessions/jobs independently from formal questions."""
import json
import uuid
from contextlib import closing
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def encode(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True)


def initialize_agent_schema(conn):
    statements=[
        '''CREATE TABLE IF NOT EXISTS ai_sessions(id TEXT PRIMARY KEY,title TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS ai_messages(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES ai_sessions(id),
           request_id TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(session_id,request_id,role))''',
        '''CREATE TABLE IF NOT EXISTS ai_attachments(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES ai_sessions(id),
           filename TEXT NOT NULL,relative_path TEXT NOT NULL,sha256 TEXT NOT NULL,width INTEGER NOT NULL,height INTEGER NOT NULL,
           created_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS ai_tasks(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES ai_sessions(id),
           state TEXT NOT NULL,payload_json TEXT NOT NULL,message TEXT NOT NULL,error TEXT,revision INTEGER NOT NULL DEFAULT 1,
           calls INTEGER NOT NULL DEFAULT 0,usage_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS ai_items(id TEXT PRIMARY KEY,task_id TEXT NOT NULL REFERENCES ai_tasks(id),
           draft_id TEXT NOT NULL UNIQUE,item_order INTEGER NOT NULL,state TEXT NOT NULL,details_json TEXT NOT NULL,
           validated_hash TEXT,question_id TEXT,revision INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS ai_publications(request_id TEXT PRIMARY KEY,task_id TEXT NOT NULL REFERENCES ai_tasks(id),
           selection_json TEXT NOT NULL,result_json TEXT NOT NULL,created_at TEXT NOT NULL)''',
        '''CREATE INDEX IF NOT EXISTS ai_items_task ON ai_items(task_id,item_order)''',
        '''CREATE TABLE IF NOT EXISTS ai_documents(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES ai_sessions(id),
           filename TEXT NOT NULL,relative_path TEXT NOT NULL,sha256 TEXT NOT NULL,page_count INTEGER NOT NULL,created_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS ai_publish_batches(request_id TEXT PRIMARY KEY,selection_json TEXT NOT NULL,result_json TEXT NOT NULL,created_at TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS ai_review_requests(request_id TEXT PRIMARY KEY,item_id TEXT NOT NULL REFERENCES ai_items(id),expected_revision INTEGER NOT NULL,approved_hash TEXT NOT NULL,created_at TEXT NOT NULL)''',
    ]
    for statement in statements:conn.execute(statement)
    columns={row['name'] for row in conn.execute('PRAGMA table_info(ai_attachments)')}
    if 'document_id' not in columns:conn.execute('ALTER TABLE ai_attachments ADD COLUMN document_id TEXT REFERENCES ai_documents(id)')
    if 'page_number' not in columns:conn.execute('ALTER TABLE ai_attachments ADD COLUMN page_number INTEGER NOT NULL DEFAULT 1')
    columns={row['name'] for row in conn.execute('PRAGMA table_info(ai_items)')}
    for name in ['reviewed_at','reviewed_hash']:
        if name not in columns:conn.execute(f'ALTER TABLE ai_items ADD COLUMN {name} TEXT')


class AgentStore:
    def __init__(self,db):
        self.db=db
        self.directory=db.path.parent/'agent'

    def sessions(self):
        with closing(self.db.connect()) as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM ai_sessions ORDER BY updated_at DESC')]

    def create_session(self,title='图片录题'):
        sid=str(uuid.uuid4());stamp=now()
        with self.db.transaction() as conn:
            conn.execute('INSERT INTO ai_sessions VALUES(?,?,?,?)',(sid,title[:80],stamp,stamp))
        return {'id':sid,'title':title[:80],'created_at':stamp,'updated_at':stamp}

    def session(self,sid,compact=False):
        with closing(self.db.connect()) as conn:
            row=conn.execute('SELECT * FROM ai_sessions WHERE id=?',(sid,)).fetchone()
            if not row:raise KeyError('录题会话不存在')
            tasks=[self.task_row(r) for r in conn.execute('SELECT * FROM ai_tasks WHERE session_id=? ORDER BY created_at DESC',(sid,))]
            if compact:
                for task in tasks:task['payload']={key:task['payload'][key] for key in ['attachment_ids','instruction','source_title','page_count'] if key in task['payload']}
            return {**dict(row),'messages':[dict(r) for r in conn.execute('SELECT * FROM ai_messages WHERE session_id=? ORDER BY created_at',(sid,))],
                    'attachments':[self.attachment_row(r) for r in conn.execute('SELECT * FROM ai_attachments WHERE session_id=? ORDER BY created_at',(sid,))],
                    'documents':[self.document_row(r) for r in conn.execute('SELECT * FROM ai_documents WHERE session_id=? ORDER BY created_at',(sid,))],
                    'tasks':tasks}

    @staticmethod
    def attachment_row(row):
        value=dict(row);value.pop('relative_path',None)
        value['url']='/api/agent/attachments/'+value['id']+'/image'
        value['kind']='page' if value.get('document_id') else 'image'
        return value

    @staticmethod
    def document_row(row):
        value=dict(row);value.pop('relative_path',None)
        value.update(kind='pdf',url='/api/agent/documents/'+value['id']+'/file')
        return value

    def document(self,did):
        with closing(self.db.connect()) as conn:
            row=conn.execute('SELECT * FROM ai_documents WHERE id=?',(did,)).fetchone()
            if not row:raise KeyError('PDF 文档不存在')
            pages=[self.attachment_row(r) for r in conn.execute('SELECT * FROM ai_attachments WHERE document_id=? ORDER BY page_number',(did,))]
            return {**self.document_row(row),'pages':pages}

    @staticmethod
    def task_row(row):
        value=dict(row);value['payload']=json.loads(value.pop('payload_json'));value['usage']=json.loads(value.pop('usage_json'))
        return value

    def attachment(self,aid):
        with closing(self.db.connect()) as conn:
            row=conn.execute('SELECT * FROM ai_attachments WHERE id=?',(aid,)).fetchone()
            if not row:raise KeyError('原图不存在')
            return dict(row)

    def task(self,tid):
        with closing(self.db.connect()) as conn:
            row=conn.execute('SELECT * FROM ai_tasks WHERE id=?',(tid,)).fetchone()
            if not row:raise KeyError('导入任务不存在')
            return self.task_row(row)

    def task_update(self,tid,**fields):
        allowed={'state','message','error','payload_json'}
        if not fields.keys()<=allowed:raise ValueError('任务更新字段无效')
        with self.db.transaction() as conn:
            conn.execute('UPDATE ai_tasks SET '+','.join(key+'=?' for key in fields)+',revision=revision+1,updated_at=? WHERE id=?',
                         [*fields.values(),now(),tid])

    def message(self,sid,role,text,request_id=None):
        self.session(sid)
        with self.db.transaction() as conn:
            conn.execute('INSERT OR IGNORE INTO ai_messages VALUES(?,?,?,?,?,?)',
                         (str(uuid.uuid4()),sid,request_id or str(uuid.uuid4()),role,text[:12_000],now()))
            conn.execute('UPDATE ai_sessions SET updated_at=? WHERE id=?',(now(),sid))

    def account_call(self,tid,usage=None):
        if not tid:return
        with self.db.transaction() as conn:
            row=conn.execute('SELECT usage_json FROM ai_tasks WHERE id=?',(tid,)).fetchone()
            if not row:return
            totals=json.loads(row[0])
            for key in ['prompt_tokens','completion_tokens','total_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens']:
                totals[key]=totals.get(key,0)+max(0,int((usage or {}).get(key,0) or 0))
            conn.execute('UPDATE ai_tasks SET calls=calls+?,usage_json=?,updated_at=? WHERE id=?',
                         (0 if usage is not None else 1,encode(totals),now(),tid))
