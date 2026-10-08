"""Transactional schema-nine migration and logical bank management primitives."""
from __future__ import annotations

import json
import sqlite3

SYSTEM_BANK_ID = 'system'


def migrate(conn: sqlite3.Connection, timestamp: str) -> None:
    """Rebuild composite keys without rewriting IDs, content or legacy AI hashes."""
    if 'bank_id' in {r['name'] for r in conn.execute('PRAGMA table_info(questions)')}:
        return
    tables = ('collections', 'topics', 'knowledge_points', 'questions', 'paper_pool', 'paper_pool_undo')
    sequence=conn.execute("SELECT seq FROM sqlite_sequence WHERE name='paper_pool'").fetchone()
    saved = {name: [dict(row) for row in conn.execute(f'SELECT * FROM {name}')] for name in tables}
    for name in reversed(tables):
        conn.execute(f'DROP TABLE {name}')
    statements = [
        '''CREATE TABLE banks(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,
            is_system INTEGER NOT NULL DEFAULT 0 CHECK(is_system IN (0,1)),
            created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''',
        '''CREATE TABLE collections(bank_id TEXT NOT NULL DEFAULT 'system' REFERENCES banks(id),
            code TEXT NOT NULL,title TEXT NOT NULL,material TEXT NOT NULL,sort_order INTEGER NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(bank_id,code),UNIQUE(bank_id,sort_order))''',
        '''CREATE TABLE topics(bank_id TEXT NOT NULL DEFAULT 'system',collection_code TEXT NOT NULL,
            code TEXT NOT NULL,title TEXT NOT NULL,sort_order INTEGER NOT NULL,
            PRIMARY KEY(bank_id,collection_code,code),
            FOREIGN KEY(bank_id,collection_code) REFERENCES collections(bank_id,code))''',
        '''CREATE TABLE knowledge_points(bank_id TEXT NOT NULL DEFAULT 'system',collection_code TEXT NOT NULL,
            topic_code TEXT NOT NULL,code TEXT NOT NULL,title TEXT NOT NULL,sort_order INTEGER NOT NULL,
            order_revision INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(bank_id,collection_code,code),
            FOREIGN KEY(bank_id,collection_code,topic_code) REFERENCES topics(bank_id,collection_code,code))''',
        '''CREATE TABLE questions(id TEXT PRIMARY KEY,bank_id TEXT NOT NULL DEFAULT 'system',
            legacy_uid TEXT UNIQUE,collection_code TEXT NOT NULL,point_code TEXT NOT NULL,position INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('single','multi','fill','long')),question_tex TEXT NOT NULL,
            options_json TEXT NOT NULL DEFAULT '[]',answer_tex TEXT NOT NULL DEFAULT '',solution_tex TEXT NOT NULL,
            sources_json TEXT NOT NULL DEFAULT '{}',verified INTEGER NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
            UNIQUE(bank_id,collection_code,point_code,position),
            FOREIGN KEY(bank_id,collection_code,point_code) REFERENCES knowledge_points(bank_id,collection_code,code))''',
        '''CREATE TABLE paper_pool(added_order INTEGER PRIMARY KEY AUTOINCREMENT,
            bank_id TEXT NOT NULL DEFAULT 'system' REFERENCES banks(id),
            question_id TEXT NOT NULL UNIQUE REFERENCES questions(id) ON DELETE CASCADE)''',
        '''CREATE TABLE paper_pool_undo(bank_id TEXT PRIMARY KEY DEFAULT 'system' REFERENCES banks(id),
            singleton INTEGER NOT NULL DEFAULT 1 CHECK(singleton=1),removed_json TEXT NOT NULL,created_at TEXT NOT NULL)''',
        '''CREATE INDEX idx_questions_scope_position ON questions(bank_id,collection_code,point_code,position)''',
        '''CREATE TRIGGER paper_pool_limit BEFORE INSERT ON paper_pool
            WHEN (SELECT COUNT(*) FROM paper_pool WHERE bank_id=NEW.bank_id)>=100
            BEGIN SELECT RAISE(ABORT,'组卷区最多保存 100 道题目'); END''',
        '''CREATE TRIGGER paper_pool_bank BEFORE INSERT ON paper_pool
            WHEN NOT EXISTS(SELECT 1 FROM questions WHERE id=NEW.question_id AND bank_id=NEW.bank_id)
            BEGIN SELECT RAISE(ABORT,'题目不属于当前题库'); END''',
        '''CREATE TABLE bank_transfers(request_id TEXT PRIMARY KEY,selection_json TEXT NOT NULL,
            result_json TEXT NOT NULL,created_at TEXT NOT NULL)''',
    ]
    for sql in statements:
        conn.execute(sql)
    conn.execute('INSERT INTO banks VALUES(?,?,?,?,?)', (SYSTEM_BANK_ID, '系统题库', 1, timestamp, timestamp))
    for name in tables:
        for row in saved[name]:
            row['bank_id'] = SYSTEM_BANK_ID
            names = ','.join(row)
            marks = ','.join('?' for _ in row)
            conn.execute(f'INSERT INTO {name}({names}) VALUES({marks})', tuple(row.values()))
    if sequence:
        current=conn.execute("SELECT seq FROM sqlite_sequence WHERE name='paper_pool'").fetchone()
        if current:conn.execute("UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name='paper_pool'",(sequence[0],))
        else:conn.execute("INSERT INTO sqlite_sequence(name,seq) VALUES('paper_pool',?)",(sequence[0],))
    # SQLite forbids adding a populated REFERENCES column with a non-null default.
    # Keep the original tables and enforce the association with insert/update guards.
    for table in ['drafts','ai_sessions']:
        conn.execute("ALTER TABLE "+table+" ADD COLUMN bank_id TEXT NOT NULL DEFAULT 'system'")
        for operation in ['INSERT','UPDATE OF bank_id']:
            name=table+'_bank_'+('insert' if operation=='INSERT' else 'update')
            conn.execute('CREATE TRIGGER '+name+' BEFORE '+operation+' ON '+table+
                         " WHEN NOT EXISTS(SELECT 1 FROM banks WHERE id=NEW.bank_id) BEGIN SELECT RAISE(ABORT,'题库不存在'); END")
    # Existing content_json deliberately stays unchanged: legacy confirmation hashes
    # cover those bytes. New drafts explicitly carry bank_id in their form.
    if conn.execute('PRAGMA foreign_key_check').fetchall():
        raise RuntimeError('多题库迁移外键校验失败，已回滚')


def seed_framework(conn, bank_id, collections):
    for code, title, material, order, topics in collections:
        conn.execute('INSERT INTO collections(bank_id,code,title,material,sort_order) VALUES(?,?,?,?,?)',
                     (bank_id, code, title, material, order))
        for topic_order, (topic, topic_title, points) in enumerate(topics, 1):
            conn.execute('INSERT INTO topics(bank_id,collection_code,code,title,sort_order) VALUES(?,?,?,?,?)',
                         (bank_id, code, topic, topic_title, topic_order))
            for point_order, (point, point_title) in enumerate(points, 1):
                conn.execute('INSERT INTO knowledge_points(bank_id,collection_code,topic_code,code,title,sort_order) VALUES(?,?,?,?,?,?)',
                             (bank_id, code, topic, point, point_title, point_order))
