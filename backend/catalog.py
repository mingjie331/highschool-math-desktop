from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import sqlite3
import threading
import uuid
from contextlib import closing, contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from .runtime import HOME, RESOURCES
from .assets import IMAGE_RE, image_references, asset_path, ASSET_LOCK

APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_DIR
DATA_DIR = Path(os.environ.get('QUESTION_VIEWER_DATA_DIR', HOME / 'data'))
ASSET_DIR = DATA_DIR / 'assets'
DB_PATH = DATA_DIR / 'question_bank.sqlite3'
SOURCE_BANK = Path(os.environ.get('QUESTION_VIEWER_SOURCE_BANK', RESOURCES / 'seed' / 'book_bank.json'))
SOURCE_LATEX = RESOURCES / 'seed'
DEFAULT_COLLECTION = 'gaoyi-first'
SCHEMA_VERSION = 9
SYSTEM_BANK_ID = 'system'
_INITIALIZE_LOCK = threading.RLock()


class PositionConflict(RuntimeError):
    def __init__(self, current_revision: int):
        super().__init__('考点题目顺序已变化，草稿已保留；请刷新目录并重新确认插入序号。')
        self.current_revision = current_revision

COLLECTIONS = [
    ('gaoyi-first', '高一上学期', '必修第一册', 1, [
        ('1', '专题一：集合与常用逻辑用语', [('1.1', '考点1：集合的概念、运算与性质'), ('1.2', '考点2：充分条件与必要条件'), ('1.3', '考点3：全称量词与存在量词')]),
        ('2', '专题二：一元二次函数、方程和不等式', [('2.1', '考点1：基本不等式（均值不等式）'), ('2.2', '考点2：一元二次不等式的解法与参数讨论')]),
        ('3', '专题三：函数的概念与性质', [('3.1', '考点1：函数的定义域与解析式求解'), ('3.2', '考点2：函数的单调性'), ('3.3', '考点3：函数的奇偶性'), ('3.4', '考点4：函数单调性与奇偶性的综合运用')]),
        ('4', '专题四：指数函数与对数函数', [('4.1', '考点1：指数与对数的运算'), ('4.2', '考点2：指数函数与对数函数的图象与性质'), ('4.3', '考点3：函数的零点与方程的根（数形结合）')]),
        ('5', '专题五：三角函数', [('5.1', '考点1：任意角与弧度制'), ('5.2', '考点2：同角三角函数基本关系与诱导公式'), ('5.3', '考点3：三角函数的图象与性质'), ('5.4', r'考点4：$y=A\sin(\omega x+\varphi)$ 的图象与变换')]),
    ]),
    ('gaoyi-second', '高一下学期', '必修第二册', 2, [
        ('6', '专题六：平面向量及其应用', [('6.1', '考点1：向量的概念、线性运算与基本定理'), ('6.2', '考点2：平面向量的数量积、夹角与模长'), ('6.3', '考点3：正弦定理与余弦定理（解三角形综合）')]),
        ('7', '专题七：复数', [('7.1', '考点1：复数的概念与几何意义'), ('7.2', '考点2：复数的代数运算')]),
        ('8', '专题八：立体几何初步', [('8.1', '考点1：空间几何体的结构特征、表面积与体积'), ('8.2', '考点2：空间点、直线、平面的位置关系'), ('8.3', '考点3：直线与平面、平面与平面平行的判定与性质'), ('8.4', '考点4：直线与平面、平面与平面垂直的判定与性质')]),
        ('9', '专题九：统计与概率初步', [('9.1', '考点1：随机抽样方法'), ('9.2', '考点2：用样本估计总体（统计图表与数字特征）'), ('9.3', '考点3：随机事件与概率（古典概型与概率的基本性质）')]),
    ]),
    ('gaokao-first', '高二上学期', '选择性必修第一册', 3, [
        ('10', '专题十：空间向量与立体几何', [('10.1', '考点1：空间向量的线性运算与数量积'), ('10.2', '考点2：空间向量在位置关系中的应用（证明平行与垂直）'), ('10.3', '考点3：空间向量在度量问题中的应用（求空间角与距离）')]),
        ('11', '专题十一：直线和圆的方程', [('11.1', '考点1：直线的倾斜角、斜率与直线方程'), ('11.2', '考点2：两直线的位置关系与距离公式'), ('11.3', '考点3：圆的方程（标准方程与一般方程）'), ('11.4', '考点4：直线与圆、圆与圆的位置关系')]),
        ('12', '专题十二：圆锥曲线的方程', [('12.1', '考点1：椭圆的定义、方程与几何性质'), ('12.2', '考点2：双曲线的定义、方程与几何性质'), ('12.3', '考点3：抛物线的定义、方程与几何性质'), ('12.4', '考点4：直线与圆锥曲线的综合（弦长、中点、面积、定点与定值问题）')]),
    ]),
    ('gaokao-second', '高二下学期', '选择性必修第二册、第三册', 4, [
        ('13', '专题十三：数列', [('13.1', '考点1：数列的概念与递推公式求通项'), ('13.2', '考点2：等差数列及其前n项和'), ('13.3', '考点3：等比数列及其前n项和'), ('13.4', '考点4：数列求和方法综合（错位相减、裂项相消、分组求和等）')]),
        ('14', '专题十四：导数及其应用', [('14.1', '考点1：导数的概念、运算与几何意义（切线方程）'), ('14.2', '考点2：利用导数研究函数的单调性'), ('14.3', '考点3：利用导数研究函数的极值与最值'), ('14.4', '考点4：导数的综合应用（恒成立问题、存在性问题、零点问题、不等式证明）')]),
        ('15', '专题十五：计数原理', [('15.1', '考点1：基本计数原理（分类加法与分步乘法）'), ('15.2', '考点2：排列与组合'), ('15.3', '考点3：二项式定理')]),
        ('16', '专题十六：离散型随机变量及其分布与统计分析', [('16.1', '考点1：条件概率、全概率公式与贝叶斯公式'), ('16.2', '考点2：离散型随机变量的分布列、期望与方差'), ('16.3', '考点3：二项分布与超几何分布'), ('16.4', '考点4：正态分布'), ('16.5', '考点5：成对数据的统计分析（一元线性回归模型、独立性检验）')]),
    ]),
    ('misc', '其他专题／未分类题目', '独立题库集合', 5, [
        ('6', '其他专题：未分类题目', [('6.1', '未分类题目')]),
        ('bridge', '初升高衔接题', [('bridge.1', '衔接练习')]),
    ]),
]
COLLECTION_MAP = {row[0]: row for row in COLLECTIONS}
# Compatibility view used by older callers: first-semester topics plus the historical misc topic.
TOPICS = COLLECTIONS[0][4] + COLLECTIONS[4][4]
SEMESTERS = COLLECTIONS[:4]
TYPE_NAMES = {'single': '单选', 'multi': '多选', 'fill': '填空', 'long': '解答'}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _plain_preview(tex: str) -> str:
    text = IMAGE_RE.sub('[图]', tex)
    text = re.sub(r'\\(?:par|noindent|quad|qquad|underline|hspace|vspace)\b(?:\{[^}]*\})?', ' ', text)
    text = re.sub(r'\\[a-zA-Z]+', '', text).replace('$', '').replace('{', '').replace('}', '')
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:90] + ('…' if len(text) > 90 else '')


def legacy_collection(point_code: str) -> str:
    if point_code == '6.1':
        return 'misc'
    for code, _, _, _, topics in COLLECTIONS:
        if any(point_code == point for _, _, points in topics for point, _ in points):
            return code
    return DEFAULT_COLLECTION


def collection_topics(code: str) -> list[tuple]:
    row = COLLECTION_MAP.get(code)
    if not row:
        raise ValueError('题库集合不存在')
    return row[4]


class CatalogDB:
    def __init__(self, path: Path = DB_PATH, source_bank: Path = SOURCE_BANK) -> None:
        self.path, self.source_bank = path, source_bank

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute('BEGIN IMMEDIATE'); yield conn; conn.commit()
        except Exception:
            conn.rollback(); raise
        finally: conn.close()

    def _schema_version(self) -> int | None:
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone():
                return 0
            row = conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if row is None:
            return 0
        if not re.fullmatch(r'\d+', str(row[0])):
            raise RuntimeError('数据库版本标记无效，未修改数据库。请使用数据备份恢复。')
        version = int(row[0])
        if version > SCHEMA_VERSION:
            raise RuntimeError(f'数据库版本 {version} 高于本程序支持的 {SCHEMA_VERSION}，未修改数据库。请使用新版程序。')
        return version

    def _migration_backup(self, version: int):
        directory = self.path.parent / 'backups'
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f'question-bank-schema-{version}-{uuid.uuid4().hex}.sqlite3'
        temporary = target.with_suffix('.tmp')
        try:
            with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(temporary)) as backup:
                    source.backup(backup)
                    if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise RuntimeError('迁移前数据库备份校验失败，未执行迁移。')
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def initialize(self) -> None:
        with _INITIALIZE_LOCK:
            version = self._schema_version()  # Read-only, before WAL, mkdir or DDL.
            if version is not None and version > SCHEMA_VERSION:
                raise RuntimeError('数据库来自更新版本，请升级程序；未修改数据库。')
            if version == SCHEMA_VERSION:
                return
            if version is not None and version < SCHEMA_VERSION:
                self._migration_backup(version)
            self._initialize()

    def _initialize(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ASSET_DIR.mkdir(parents=True, exist_ok=True)
        # Execute DDL individually: sqlite3.executescript commits implicitly and
        # would otherwise leave a half-migrated user database after an error.
        with self.transaction() as conn:
            columns = {row['name'] for row in conn.execute('PRAGMA table_info(questions)')}
            if 'bank_id' in columns:
                for table,name,declaration in [('knowledge_points','order_revision','INTEGER NOT NULL DEFAULT 1'),('drafts','position_mode','TEXT'),('drafts','target_order_revision','INTEGER')]:
                    if name not in {r['name'] for r in conn.execute('PRAGMA table_info('+table+')')}:conn.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+declaration)
                from .agent_store import initialize_agent_schema
                initialize_agent_schema(conn)
                conn.execute("INSERT OR REPLACE INTO metadata VALUES('schema_version',?)",(str(SCHEMA_VERSION),))
                return
            legacy = bool(columns and 'collection_code' not in columns)
            if legacy:
                for table in ('questions', 'knowledge_points', 'topics'):
                    conn.execute(f'ALTER TABLE {table} RENAME TO {table}_legacy')
            schema = """
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collections (
                    code TEXT PRIMARY KEY, title TEXT NOT NULL, material TEXT NOT NULL,
                    sort_order INTEGER NOT NULL UNIQUE, revision INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS topics (
                    collection_code TEXT NOT NULL REFERENCES collections(code), code TEXT NOT NULL,
                    title TEXT NOT NULL, sort_order INTEGER NOT NULL, PRIMARY KEY(collection_code, code));
                CREATE TABLE IF NOT EXISTS knowledge_points (
                    collection_code TEXT NOT NULL, topic_code TEXT NOT NULL, code TEXT NOT NULL,
                    title TEXT NOT NULL, sort_order INTEGER NOT NULL, PRIMARY KEY(collection_code, code),
                    FOREIGN KEY(collection_code, topic_code) REFERENCES topics(collection_code, code));
                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY, legacy_uid TEXT UNIQUE, collection_code TEXT NOT NULL,
                    point_code TEXT NOT NULL, position INTEGER NOT NULL,
                    type TEXT NOT NULL CHECK(type IN ('single','multi','fill','long')),
                    question_tex TEXT NOT NULL, options_json TEXT NOT NULL DEFAULT '[]',
                    answer_tex TEXT NOT NULL DEFAULT '', solution_tex TEXT NOT NULL,
                    sources_json TEXT NOT NULL DEFAULT '{}', verified INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(collection_code, point_code, position),
                    FOREIGN KEY(collection_code, point_code) REFERENCES knowledge_points(collection_code, code));
                CREATE TABLE IF NOT EXISTS drafts (
                    id TEXT PRIMARY KEY, source_question_id TEXT UNIQUE, source_collection_code TEXT,
                    base_revision INTEGER, content_json TEXT NOT NULL, revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS closed_drafts (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, result_json TEXT);
                CREATE TABLE IF NOT EXISTS paper_pool (
                    added_order INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id TEXT NOT NULL UNIQUE REFERENCES questions(id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS paper_pool_undo (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), removed_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_questions_scope_position ON questions(collection_code, point_code, position);
            """
            for statement in schema.split(';'):
                if statement.strip():
                    conn.execute(statement)
            conn.execute("""CREATE TRIGGER IF NOT EXISTS paper_pool_limit BEFORE INSERT ON paper_pool
                WHEN (SELECT COUNT(*) FROM paper_pool)>=100
                BEGIN SELECT RAISE(ABORT, '组卷区最多保存 100 道题目'); END""")
            if 'revision' not in {r['name'] for r in conn.execute('PRAGMA table_info(collections)')}:
                conn.execute('ALTER TABLE collections ADD COLUMN revision INTEGER NOT NULL DEFAULT 1')
            if 'source_collection_code' not in {r['name'] for r in conn.execute('PRAGMA table_info(drafts)')}:
                conn.execute('ALTER TABLE drafts ADD COLUMN source_collection_code TEXT')
            if 'order_revision' not in {r['name'] for r in conn.execute('PRAGMA table_info(knowledge_points)')}:
                conn.execute('ALTER TABLE knowledge_points ADD COLUMN order_revision INTEGER NOT NULL DEFAULT 1')
            for name, declaration in [('position_mode', 'TEXT'), ('target_order_revision', 'INTEGER')]:
                if name not in {r['name'] for r in conn.execute('PRAGMA table_info(drafts)')}:
                    conn.execute(f'ALTER TABLE drafts ADD COLUMN {name} {declaration}')
            self._seed_collections(conn)
            if legacy:
                conn.execute("""INSERT INTO questions(id,legacy_uid,collection_code,point_code,position,type,
                    question_tex,options_json,answer_tex,solution_tex,sources_json,verified,revision,created_at,updated_at)
                    SELECT id,legacy_uid,CASE WHEN point_code='6.1' THEN 'misc' ELSE 'gaoyi-first' END,
                    point_code,position,type,question_tex,options_json,answer_tex,solution_tex,sources_json,
                    verified,revision,created_at,updated_at FROM questions_legacy""")
                for table in ('questions', 'knowledge_points', 'topics'):
                    conn.execute(f'DROP TABLE {table}_legacy')
            # Before collections existed, 6.1 always meant the miscellaneous bank.
            # Preserve all other draft input, source/base versions and timestamps.
            for row in conn.execute('SELECT * FROM drafts').fetchall():
                content = json.loads(row['content_json'])
                form = content['form']
                if not form.get('collection_code'):
                    form['collection_code'] = legacy_collection(form.get('point_code', '1.1'))
                    conn.execute('UPDATE drafts SET content_json=? WHERE id=?',
                                 (json.dumps(content, ensure_ascii=False, sort_keys=True), row['id']))
                if row['source_collection_code'] is None:
                    original = conn.execute('SELECT collection_code FROM questions WHERE id=?',
                                            (row['source_question_id'],)).fetchone()
                    conn.execute('UPDATE drafts SET source_collection_code=? WHERE id=?',
                                 (original[0] if original else form['collection_code'], row['id']))
            conn.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('catalog_revision','1')")
            if not conn.execute("SELECT 1 FROM metadata WHERE key='source_imported'").fetchone():
                self._import_source(conn)
            self._migrate_bridge(conn)
            from .agent_store import initialize_agent_schema
            initialize_agent_schema(conn)
            if conn.execute('PRAGMA foreign_key_check').fetchone():
                raise RuntimeError('迁移完整性检查失败，所有迁移更改已回滚')
            self._migrate_banks(conn)
            conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))

    @staticmethod
    def _migrate_banks(conn):
        from .banks import migrate
        migrate(conn, utc_now())

    @staticmethod
    def _migrate_bridge(conn):
        if conn.execute("SELECT 1 FROM metadata WHERE key='bridge_migrated'").fetchone():
            return
        rows = conn.execute("SELECT * FROM questions WHERE collection_code='misc' AND point_code='6.1' ORDER BY position").fetchall()
        original = {row['id']: row for row in rows}
        bridge = []
        unclassified = []
        for row in rows:
            q = CatalogDB._row_to_question(row)
            (bridge if image_references(q) else unclassified).append(row['id'])
        # Move both groups through unique temporary positions in the same transaction.
        for index, row in enumerate(rows, 1):
            conn.execute('UPDATE questions SET position=? WHERE id=?', (-index, row['id']))
        now = utc_now()
        moved = {}
        for point, ids in (('6.1', unclassified), ('bridge.1', bridge)):
            for position, qid in enumerate(ids, 1):
                row = original[qid]
                changed = point != row['point_code'] or position != row['position']
                if changed:
                    conn.execute('UPDATE questions SET point_code=?,position=?,revision=revision+1,updated_at=? WHERE id=?',
                                 (point, position, now, qid))
                    moved[qid] = (row, point, position)
                else:
                    conn.execute('UPDATE questions SET point_code=?,position=? WHERE id=?', (point, position, qid))
        for draft in conn.execute('SELECT * FROM drafts WHERE source_question_id IS NOT NULL').fetchall():
            change = moved.get(draft['source_question_id'])
            if not change:
                continue
            old, point, position = change
            content = json.loads(draft['content_json'])
            form = content['form']
            if form.get('collection_code') == 'misc' and form.get('point_code') == old['point_code']:
                form['point_code'] = point
                if str(form.get('position')) == str(old['position']):
                    form['position'] = position
            base = old['revision'] + 1 if draft['base_revision'] == old['revision'] else draft['base_revision']
            conn.execute('UPDATE drafts SET content_json=?,base_revision=? WHERE id=?',
                         (json.dumps(content, ensure_ascii=False, sort_keys=True), base, draft['id']))
        if moved:
            CatalogDB._bump_revision(conn, 'misc')
        conn.execute("INSERT INTO metadata(key,value) VALUES('bridge_migrated',?)", (json.dumps({'moved': len(bridge), 'retained': len(unclassified)}),))

    @staticmethod
    def _seed_collections(conn):
        for code, title, material, order, topics in COLLECTIONS:
            conn.execute('INSERT INTO collections(code,title,material,sort_order) VALUES(?,?,?,?) '
                         'ON CONFLICT(code) DO UPDATE SET title=excluded.title,material=excluded.material,sort_order=excluded.sort_order',
                         (code, title, material, order))
            for topic_order, (topic_code, topic_title, points) in enumerate(topics, 1):
                conn.execute('INSERT INTO topics(collection_code,code,title,sort_order) VALUES(?,?,?,?) '
                             'ON CONFLICT(collection_code,code) DO UPDATE SET title=excluded.title,sort_order=excluded.sort_order',
                             (code, topic_code, topic_title, topic_order))
                for point_order, (point_code, point_title) in enumerate(points, 1):
                    conn.execute('INSERT INTO knowledge_points(collection_code,topic_code,code,title,sort_order) VALUES(?,?,?,?,?) '
                                 'ON CONFLICT(collection_code,code) DO UPDATE SET topic_code=excluded.topic_code,title=excluded.title,sort_order=excluded.sort_order',
                                 (code, topic_code, point_code, point_title, point_order))

    def _import_source(self, conn):
        if not self.source_bank.exists(): raise FileNotFoundError(f'初始题库不存在：{self.source_bank}')
        records = json.loads(self.source_bank.read_text(encoding='utf-8')); valid = {(c,p) for c,_,_,_,topics in COLLECTIONS for _,_,points in topics for p,_ in points}
        counters = {point: 0 for point in valid}
        for q in sorted(records, key=lambda item: int(item.get('book_number', 0))):
            point = str(q.get('topic', '6.1')); collection = q.get('collection_code') or legacy_collection(point)
            if (collection, point) not in valid: point, collection = '6.1', 'misc'
            counters[(collection, point)] += 1; now = utc_now(); legacy_uid = str(q.get('uid') or f"legacy-{q.get('book_number')}")
            conn.execute('INSERT INTO questions(id,legacy_uid,collection_code,point_code,position,type,question_tex,options_json,answer_tex,solution_tex,sources_json,verified,revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (str(uuid.uuid5(uuid.NAMESPACE_URL, 'gaoyi-question-bank:'+legacy_uid)),legacy_uid,collection,point,counters[(collection, point)],q.get('type','long'),q.get('question_tex',''),json.dumps(q.get('options',[]),ensure_ascii=False),q.get('answer_tex',''),q.get('solution_tex',''),json.dumps({'origins':q.get('origins',[]),'source_refs':q.get('source_refs',[]),'original_number':q.get('original_number')},ensure_ascii=False),1 if q.get('verified') else 0,1,now,now))
            self._copy_referenced_assets(q)
        conn.execute('INSERT INTO metadata(key,value) VALUES(?,?)', ('source_imported', json.dumps({'count':len(records),'at':utc_now()},ensure_ascii=False)))

    @staticmethod
    def _copy_referenced_assets(q):
        for relative in image_references(q):
            source, target = asset_path(SOURCE_LATEX, relative), asset_path(DATA_DIR, relative, require_file=False)
            if not target.exists(): target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)

    @staticmethod
    def _get_revision(conn):
        return int(conn.execute("SELECT value FROM metadata WHERE key='catalog_revision'").fetchone()[0])

    @staticmethod
    def _bump_revision(conn, *collections, bank_id=SYSTEM_BANK_ID):
        modern = 'bank_id' in {r['name'] for r in conn.execute('PRAGMA table_info(collections)')}
        for code in set(collections):
            if modern:
                conn.execute('UPDATE collections SET revision=revision+1 WHERE bank_id=? AND code=?', (bank_id, code))
            else:
                conn.execute('UPDATE collections SET revision=revision+1 WHERE code=?', (code,))
        revision = CatalogDB._get_revision(conn) + 1
        conn.execute("UPDATE metadata SET value=? WHERE key='catalog_revision'", (str(revision),))
        return revision

    @staticmethod
    def _require_bank(conn, bank_id):
        row = conn.execute('SELECT * FROM banks WHERE id=?', (bank_id,)).fetchone()
        if not row:
            raise ValueError('题库不存在')
        return row

    def list_banks(self):
        with closing(self.connect()) as conn:
            return [{**dict(row), 'count': conn.execute('SELECT COUNT(*) FROM questions WHERE bank_id=?', (row['id'],)).fetchone()[0]}
                    for row in conn.execute('SELECT * FROM banks ORDER BY is_system DESC,created_at,id')]

    @staticmethod
    def _bank_name(name):
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise ValueError('题库名称须为 1 至 80 个字符')
        return name.strip()

    def create_bank(self, name):
        from .banks import seed_framework
        name = self._bank_name(name)
        with self.transaction() as conn:
            if conn.execute('SELECT 1 FROM banks WHERE name=?', (name,)).fetchone():
                raise ValueError('题库名称已存在')
            bank_id, stamp = str(uuid.uuid4()), utc_now()
            conn.execute('INSERT INTO banks VALUES(?,?,?,?,?)', (bank_id, name, 0, stamp, stamp))
            seed_framework(conn, bank_id, COLLECTIONS)
            self._bump_revision(conn, bank_id=bank_id)
            return {**dict(self._require_bank(conn, bank_id)), 'count': 0}

    def rename_bank(self, bank_id, name):
        name = self._bank_name(name)
        with self.transaction() as conn:
            self._require_bank(conn, bank_id)
            if conn.execute('SELECT 1 FROM banks WHERE name=? AND id<>?', (name, bank_id)).fetchone():
                raise ValueError('题库名称已存在')
            conn.execute('UPDATE banks SET name=?,updated_at=? WHERE id=?', (name, utc_now(), bank_id))
            self._bump_revision(conn, bank_id=bank_id)
            return dict(self._require_bank(conn, bank_id))

    def delete_bank(self, bank_id):
        with self.transaction() as conn:
            bank = self._require_bank(conn, bank_id)
            if bank['is_system']:
                raise ValueError('系统题库不能删除')
            for table in ('questions', 'drafts'):
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    if conn.execute(f'SELECT 1 FROM {table} WHERE bank_id=? LIMIT 1', (bank_id,)).fetchone():
                        raise ValueError('题库仍有题目、草稿或 AI 会话，请先处理后再删除')
            for table in ('ai_tasks','ai_attachments','ai_documents'):
                if conn.execute('SELECT 1 FROM '+table+' WHERE session_id IN (SELECT id FROM ai_sessions WHERE bank_id=?) LIMIT 1',(bank_id,)).fetchone():
                    raise ValueError('题库仍有 AI 材料或任务，请先处理后再删除')
            conn.execute('DELETE FROM ai_messages WHERE session_id IN (SELECT id FROM ai_sessions WHERE bank_id=?)',(bank_id,))
            conn.execute('DELETE FROM ai_sessions WHERE bank_id=?',(bank_id,))
            conn.execute('DELETE FROM paper_pool_undo WHERE bank_id=?', (bank_id,))
            for table in ('knowledge_points', 'topics', 'collections'):
                conn.execute(f'DELETE FROM {table} WHERE bank_id=?', (bank_id,))
            conn.execute('DELETE FROM banks WHERE id=?', (bank_id,))
            self._bump_revision(conn)
            return {'id': bank_id, 'deleted': True}

    def point_exists(self, point_code, collection_code=DEFAULT_COLLECTION, bank_id=SYSTEM_BANK_ID):
        with closing(self.connect()) as conn:
            return conn.execute('SELECT 1 FROM knowledge_points WHERE bank_id=? AND collection_code=? AND code=?',
                                (bank_id, collection_code, point_code)).fetchone() is not None

    def point_count(self, point_code, collection_code=DEFAULT_COLLECTION, bank_id=SYSTEM_BANK_ID):
        with closing(self.connect()) as conn:
            self._require_bank(conn, bank_id)
            return conn.execute('SELECT COUNT(*) FROM questions WHERE bank_id=? AND collection_code=? AND point_code=?',
                                (bank_id, collection_code, point_code)).fetchone()[0]

    def _summary(self, conn, collection_code, topic_code, point_code, bank_id=SYSTEM_BANK_ID):
        rows = conn.execute('SELECT id,bank_id,position,type,question_tex,revision FROM questions WHERE bank_id=? AND collection_code=? AND point_code=? ORDER BY position',
                            (bank_id, collection_code, point_code))
        return [{'id': r['id'], 'bank_id': r['bank_id'], 'local_number': r['position'], 'type': r['type'],
                 'type_name': TYPE_NAMES[r['type']], 'preview': _plain_preview(r['question_tex']), 'revision': r['revision']} for r in rows]

    def _collection_catalog(self, conn, collection_code, bank_id=SYSTEM_BANK_ID):
        meta = conn.execute('SELECT * FROM collections WHERE bank_id=? AND code=?', (bank_id, collection_code)).fetchone()
        if not meta:
            raise ValueError('题库集合不存在')
        topics = []
        for topic in conn.execute('SELECT * FROM topics WHERE bank_id=? AND collection_code=? ORDER BY sort_order', (bank_id, collection_code)):
            points = []
            for point in conn.execute('SELECT * FROM knowledge_points WHERE bank_id=? AND collection_code=? AND topic_code=? ORDER BY sort_order', (bank_id, collection_code, topic['code'])):
                questions = self._summary(conn, collection_code, topic['code'], point['code'], bank_id)
                points.append({'code': point['code'], 'title': point['title'], 'count': len(questions), 'order_revision': point['order_revision'], 'questions': questions})
            topics.append({'code': topic['code'], 'title': topic['title'], 'count': sum(p['count'] for p in points), 'points': points})
        return {'bank_id': bank_id, 'code': meta['code'], 'title': meta['title'], 'material': meta['material'],
                'count': sum(t['count'] for t in topics), 'revision': meta['revision'], 'topics': topics}

    def catalog(self, bank_id=SYSTEM_BANK_ID):
        with closing(self.connect()) as conn:
            conn.execute('BEGIN')
            bank = dict(self._require_bank(conn, bank_id))
            collections = [self._collection_catalog(conn, row['code'], bank_id) for row in conn.execute('SELECT code FROM collections WHERE bank_id=? ORDER BY sort_order', (bank_id,))]
            legacy = [t for c in collections if c['code'] in (DEFAULT_COLLECTION, 'misc') for t in c['topics']]
            return {'bank_id': bank_id, 'bank_name': bank['name'], 'bank': bank, 'revision': self._get_revision(conn),
                    'total': sum(c['count'] for c in collections), 'collections': collections,
                    'semesters': [c for c in collections if c['code'] != 'misc'], 'topics': legacy}

    def get_question(self, question_id):
        with closing(self.connect()) as conn:
            return self._question_in(conn, question_id)

    def _question_in(self, conn, question_id):
        row = conn.execute('SELECT q.*,p.order_revision FROM questions q JOIN knowledge_points p '
                           'ON p.bank_id=q.bank_id AND p.collection_code=q.collection_code AND p.code=q.point_code WHERE q.id=?', (question_id,)).fetchone()
        return self._row_to_question(row) if row else None

    @staticmethod
    def _row_to_question(row):
        return {'id': row['id'], 'bank_id': row['bank_id'] if 'bank_id' in row.keys() else SYSTEM_BANK_ID,
                'legacy_uid': row['legacy_uid'], 'collection_code': row['collection_code'], 'point_code': row['point_code'],
                'position': row['position'], 'type': row['type'], 'question_tex': row['question_tex'],
                'options': json.loads(row['options_json']), 'answer_tex': row['answer_tex'], 'solution_tex': row['solution_tex'],
                'sources': json.loads(row['sources_json']), 'verified': bool(row['verified']), 'revision': row['revision'],
                'order_revision': row['order_revision'] if 'order_revision' in row.keys() else None,
                'created_at': row['created_at'], 'updated_at': row['updated_at']}

    def collection_state(self, collection_code=DEFAULT_COLLECTION, bank_id=SYSTEM_BANK_ID):
        with closing(self.connect()) as conn:
            conn.execute('BEGIN')
            self._require_bank(conn, bank_id)
            row = conn.execute('SELECT revision FROM collections WHERE bank_id=? AND code=?', (bank_id, collection_code)).fetchone()
            if not row:
                raise ValueError('题库集合不存在')
            count = conn.execute('SELECT count(*) FROM questions WHERE bank_id=? AND collection_code=?', (bank_id, collection_code)).fetchone()[0]
            return row[0], count

    def ordered_snapshot(self, collection_code=DEFAULT_COLLECTION, bank_id=SYSTEM_BANK_ID):
        with closing(self.connect()) as conn:
            conn.execute('BEGIN')
            self._require_bank(conn, bank_id)
            row = conn.execute('SELECT revision FROM collections WHERE bank_id=? AND code=?', (bank_id, collection_code)).fetchone()
            if not row:
                raise ValueError('题库集合不存在')
            rows = conn.execute("""SELECT q.*,p.order_revision FROM questions q JOIN knowledge_points p
                ON p.bank_id=q.bank_id AND p.collection_code=q.collection_code AND p.code=q.point_code
                JOIN topics t ON t.bank_id=p.bank_id AND t.collection_code=p.collection_code AND t.code=p.topic_code
                WHERE q.bank_id=? AND q.collection_code=? ORDER BY t.sort_order,p.sort_order,q.position""", (bank_id, collection_code)).fetchall()
            return row[0], [self._row_to_question(r) for r in rows]

    def collection_snapshot(self, collection_code=DEFAULT_COLLECTION, bank_id=SYSTEM_BANK_ID):
        with ASSET_LOCK:
            revision, questions = self.ordered_snapshot(collection_code, bank_id)
            assets = {ref: asset_path(DATA_DIR, ref).read_bytes() for question in questions for ref in image_references(question)}
            return revision, questions, assets, (RESOURCES / 'preamble.tex').read_bytes()

    def point_order_revision(self, collection_code, point_code, _conn=None, bank_id=SYSTEM_BANK_ID):
        with (nullcontext(_conn) if _conn is not None else closing(self.connect())) as conn:
            row = conn.execute('SELECT order_revision FROM knowledge_points WHERE bank_id=? AND collection_code=? AND code=?', (bank_id, collection_code, point_code)).fetchone()
            if not row:
                raise ValueError('考点不存在')
            return int(row[0])

    def _check_position(self, conn, data, require=False):
        current = self.point_order_revision(data['collection_code'], data['point_code'], conn, data.get('bank_id', SYSTEM_BANK_ID))
        expected = data.get('target_order_revision')
        if (require and expected is None) or (expected is not None and expected != current):
            raise PositionConflict(current)

    def _bump_order_if_changed(self, conn, collection, point, before, bank_id=SYSTEM_BANK_ID):
        if before != self._ids_for_point(conn, collection, point, bank_id=bank_id):
            conn.execute('UPDATE knowledge_points SET order_revision=order_revision+1 WHERE bank_id=? AND collection_code=? AND code=?', (bank_id, collection, point))

    def _ids_for_point(self, conn, collection_code, point_code, exclude=None, bank_id=SYSTEM_BANK_ID):
        sql = 'SELECT id FROM questions WHERE bank_id=? AND collection_code=? AND point_code=?'
        args = [bank_id, collection_code, point_code]
        if exclude:
            sql += ' AND id<>?'
            args.append(exclude)
        return [row[0] for row in conn.execute(sql + ' ORDER BY position', args)]

    @staticmethod
    def _resequence(conn, collection_code, point_code, ids, bank_id=SYSTEM_BANK_ID):
        for i, qid in enumerate(ids, 1):
            conn.execute('UPDATE questions SET position=? WHERE id=? AND bank_id=?', (-i, qid, bank_id))
        for i, qid in enumerate(ids, 1):
            conn.execute('UPDATE questions SET collection_code=?,point_code=?,position=? WHERE id=? AND bank_id=?', (collection_code, point_code, i, qid, bank_id))

    def create_question(self, data, _conn=None):
        bank_id = data.get('bank_id', SYSTEM_BANK_ID)
        point = data['point_code']
        collection = data.get('collection_code') or legacy_collection(point)
        with ASSET_LOCK, (nullcontext(_conn) if _conn is not None else self.transaction()) as conn:
            self._require_bank(conn, bank_id)
            self._check_position(conn, {**data, 'collection_code': collection, 'bank_id': bank_id})
            for ref in image_references(data):
                asset_path(DATA_DIR, ref)
            ids = self._ids_for_point(conn, collection, point, bank_id=bank_id)
            before, position = list(ids), int(data['position'])
            if not 1 <= position <= len(ids) + 1:
                raise ValueError(f'插入序号必须在 1 到 {len(ids)+1} 之间')
            qid, stamp = str(uuid.uuid4()), utc_now()
            conn.execute('INSERT INTO questions(id,bank_id,collection_code,point_code,position,type,question_tex,options_json,answer_tex,solution_tex,sources_json,verified,revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (qid, bank_id, collection, point, -len(ids)-1, data['type'], data['question_tex'], json.dumps(data.get('options', []), ensure_ascii=False), data.get('answer_tex', ''), data['solution_tex'], json.dumps(data.get('sources', {}), ensure_ascii=False), int(bool(data.get('verified'))), 1, stamp, stamp))
            ids.insert(position-1, qid)
            self._resequence(conn, collection, point, ids, bank_id)
            self._bump_order_if_changed(conn, collection, point, before, bank_id)
            revision = self._bump_revision(conn, collection, bank_id=bank_id)
            return revision, self._question_in(conn, qid)

    def update_question(self, question_id, expected_revision, data, _conn=None):
        with ASSET_LOCK, (nullcontext(_conn) if _conn is not None else self.transaction()) as conn:
            old = conn.execute('SELECT * FROM questions WHERE id=?', (question_id,)).fetchone()
            if not old:
                raise KeyError('题目不存在')
            bank_id = old['bank_id']
            if data.get('bank_id', bank_id) != bank_id:
                raise ValueError('跨题库移动请使用批量移动功能')
            if old['revision'] != expected_revision:
                raise RuntimeError('题目已在另一个窗口中修改，请刷新后重试')
            target = data['point_code']
            collection = data.get('collection_code') or (old['collection_code'] if conn.execute('SELECT 1 FROM knowledge_points WHERE bank_id=? AND collection_code=? AND code=?', (bank_id, old['collection_code'], target)).fetchone() else legacy_collection(target))
            if not conn.execute('SELECT 1 FROM knowledge_points WHERE bank_id=? AND collection_code=? AND code=?', (bank_id, collection, target)).fetchone():
                raise ValueError('考点不存在')
            for ref in image_references(data):
                asset_path(DATA_DIR, ref)
            same = collection == old['collection_code'] and target == old['point_code']
            old_order = self._ids_for_point(conn, old['collection_code'], old['point_code'], bank_id=bank_id)
            target_order = old_order if same else self._ids_for_point(conn, collection, target, bank_id=bank_id)
            if data.get('position_mode') == 'keep':
                if not same:
                    raise ValueError('跨考点移动需要确认插入序号')
                position = old['position']
            else:
                self._check_position(conn, {**data, 'collection_code': collection, 'bank_id': bank_id})
                position = int(data['position'])
            old_ids = [i for i in old_order if i != question_id]
            target_ids = old_ids if same else list(target_order)
            if not 1 <= position <= len(target_ids) + 1:
                raise ValueError(f'目标序号必须在 1 到 {len(target_ids)+1} 之间')
            conn.execute('UPDATE questions SET position=-999999 WHERE id=?', (question_id,))
            self._resequence(conn, old['collection_code'], old['point_code'], old_ids, bank_id)
            target_ids.insert(position-1, question_id)
            self._resequence(conn, collection, target, target_ids, bank_id)
            conn.execute('UPDATE questions SET type=?,question_tex=?,options_json=?,answer_tex=?,solution_tex=?,sources_json=?,verified=?,revision=revision+1,updated_at=? WHERE id=?',
                         (data['type'], data['question_tex'], json.dumps(data.get('options', []), ensure_ascii=False), data.get('answer_tex', ''), data['solution_tex'], json.dumps(data.get('sources', {}), ensure_ascii=False), int(bool(data.get('verified'))), utc_now(), question_id))
            self._bump_order_if_changed(conn, old['collection_code'], old['point_code'], old_order, bank_id)
            if not same:
                self._bump_order_if_changed(conn, collection, target, target_order, bank_id)
            revision = self._bump_revision(conn, old['collection_code'], collection, bank_id=bank_id)
            return revision, self._question_in(conn, question_id)

    def delete_question(self, question_id, expected_revision, bank_id=None):
        with ASSET_LOCK, self.transaction() as conn:
            row = conn.execute('SELECT * FROM questions WHERE id=?', (question_id,)).fetchone()
            if not row:
                raise KeyError('题目不存在')
            if bank_id is not None and row['bank_id'] != bank_id:
                raise ValueError('题目不属于当前题库')
            bank_id = row['bank_id']
            if row['revision'] != expected_revision:
                raise RuntimeError('题目已在另一个窗口中修改，请刷新后重试')
            before = self._ids_for_point(conn, row['collection_code'], row['point_code'], bank_id=bank_id)
            removed = self._row_to_question(row)
            conn.execute('DELETE FROM questions WHERE id=?', (question_id,))
            self._resequence(conn, row['collection_code'], row['point_code'], [i for i in before if i != question_id], bank_id)
            self._bump_order_if_changed(conn, row['collection_code'], row['point_code'], before, bank_id)
            return self._bump_revision(conn, row['collection_code'], bank_id=bank_id), removed

    def asset_is_referenced(self, latex_path, _conn=None):
        target = asset_path(DATA_DIR, latex_path, require_file=False)
        with (nullcontext(_conn) if _conn is not None else closing(self.connect())) as conn:
            records = [self._row_to_question(r) for r in conn.execute('SELECT * FROM questions')]
            records.extend(json.loads(r[0])['form'] for r in conn.execute('SELECT content_json FROM drafts'))
            for record in records:
                for ref in image_references(record):
                    try:
                        if asset_path(DATA_DIR, ref, require_file=False) == target:
                            return True
                    except ValueError:
                        continue
        return False

    def transfer_questions(self, selection, target_bank_id, mode, source_bank_id=SYSTEM_BANK_ID, request_id=None):
        if mode not in {'move', 'copy'} or not selection or len({q['id'] for q in selection}) != len(selection):
            raise ValueError('请选择不重复题目并指定移动或复制')
        signature=json.dumps([source_bank_id,target_bank_id,mode,selection],sort_keys=True)
        with ASSET_LOCK,self.transaction() as conn:
            self._require_bank(conn,target_bank_id);self._require_bank(conn,source_bank_id)
            if source_bank_id==target_bank_id:raise ValueError('请选择不同的目标题库')
            if request_id:
                previous=conn.execute('SELECT * FROM bank_transfers WHERE request_id=?',(request_id,)).fetchone()
                if previous:
                    if previous['selection_json']!=signature:raise RuntimeError('请求已用于不同操作')
                    return json.loads(previous['result_json'])
            rows=[]
            for item in selection:
                q=self._question_in(conn,item['id'])
                if not q or q['bank_id']!=source_bank_id:raise ValueError('题目不属于当前题库')
                if q['revision']!=item['revision']:raise RuntimeError('题目已变化，请刷新后重试')
                if conn.execute('SELECT 1 FROM drafts WHERE source_question_id=?',(q['id'],)).fetchone():raise RuntimeError('所选题目有编辑草稿，请先保存或处理草稿')
                rows.append(q)
            order={q['id']:i for i,q in enumerate(self.ordered_snapshot_all(source_bank_id))}
            rows.sort(key=lambda q:order[q['id']]);result=[]
            for q in rows:
                target={**q,'bank_id':target_bank_id,'position':len(self._ids_for_point(conn,q['collection_code'],q['point_code'],bank_id=target_bank_id))+1,'position_mode':'move','target_order_revision':None}
                # Content and immutable assets can be copied without recompilation.
                _,copied=self.create_question(target,conn)
                if mode=='move':
                    old_order=self._ids_for_point(conn,q['collection_code'],q['point_code'],bank_id=source_bank_id)
                    conn.execute('DELETE FROM paper_pool WHERE question_id=?',(q['id'],))
                    conn.execute('DELETE FROM questions WHERE id=?',(q['id'],))
                    conn.execute('UPDATE questions SET id=?,legacy_uid=?,revision=?,created_at=? WHERE id=?',(q['id'],q['legacy_uid'],q['revision']+1,q['created_at'],copied['id']))
                    self._resequence(conn,q['collection_code'],q['point_code'],[i for i in old_order if i!=q['id']],source_bank_id)
                    self._bump_order_if_changed(conn,q['collection_code'],q['point_code'],old_order,source_bank_id)
                    self._bump_revision(conn,q['collection_code'],bank_id=source_bank_id)
                    copied=self._question_in(conn,q['id'])
                result.append({'source_id':q['id'],'id':copied['id'],'bank_id':target_bank_id})
            value={'items':result,'mode':mode,'source_bank_id':source_bank_id,'target_bank_id':target_bank_id}
            if request_id:conn.execute('INSERT INTO bank_transfers VALUES(?,?,?,?)',(request_id,signature,json.dumps(value,ensure_ascii=False),utc_now()))
            return value

    def cleanup_assets(self, removed):
        with ASSET_LOCK, self.transaction() as conn:
            for ref in image_references(removed):
                try:
                    candidate=asset_path(DATA_DIR,ref,require_file=False)
                    if re.fullmatch(r'[0-9a-f-]{36}\.(png|jpg|jpeg|pdf)',candidate.name,re.I) and candidate.is_file() and not self.asset_is_referenced(ref,conn): candidate.unlink()
                except (ValueError,OSError): pass

    @staticmethod
    def _draft(row):
        result=dict(row); result['content']=json.loads(result.pop('content_json')); return result
    def list_drafts(self, bank_id=SYSTEM_BANK_ID):
        with closing(self.connect()) as conn: return [self._draft(r) for r in conn.execute('SELECT * FROM drafts WHERE bank_id=? ORDER BY updated_at DESC,id', (bank_id,))]
    def get_draft(self,draft_id):
        with closing(self.connect()) as conn:
            row=conn.execute('SELECT * FROM drafts WHERE id=?',(draft_id,)).fetchone()
            if not row: raise KeyError('草稿不存在或已发布/丢弃')
            return self._draft(row)
    def save_draft(self, draft_id, expected, source_id, base_revision, content,
                   position_mode=None, target_order_revision=None, bank_id=None):
        if position_mode not in (None, 'keep', 'move'):
            raise ValueError('位置保存方式无效')
        if target_order_revision is not None and (not isinstance(target_order_revision, int) or target_order_revision < 1):
            raise ValueError('排列版本无效')
        content = json.loads(json.dumps(content, ensure_ascii=False))
        with self.transaction() as conn:
            if conn.execute('SELECT 1 FROM closed_drafts WHERE id=?', (draft_id,)).fetchone():
                raise RuntimeError('草稿已发布或丢弃，请重新打开编辑器')
            old = conn.execute('SELECT * FROM drafts WHERE id=?', (draft_id,)).fetchone()
            original = conn.execute('SELECT collection_code,bank_id FROM questions WHERE id=?', (source_id,)).fetchone()
            form = content['form']
            resolved_bank = bank_id or form.get('bank_id') or (old['bank_id'] if old else (original['bank_id'] if original else SYSTEM_BANK_ID))
            self._require_bank(conn, resolved_bank)
            if (old and old['bank_id'] != resolved_bank) or (original and original['bank_id'] != resolved_bank):
                raise ValueError('草稿或原题不属于当前题库')
            form['bank_id'] = resolved_bank
            if not form.get('collection_code'):
                point = form.get('point_code', '1.1')
                # Legacy clients omit scope. Keep the draft's target first, then
                # the source scope, so the two meanings of 6.1 never get swapped.
                prior_scope = json.loads(old['content_json'])['form'].get('collection_code') if old else None
                candidates = [prior_scope, original[0] if original else None]
                form['collection_code'] = next((scope for scope in candidates if scope and conn.execute(
                    'SELECT 1 FROM knowledge_points WHERE bank_id=? AND collection_code=? AND code=?', (resolved_bank, scope, point)
                ).fetchone()), legacy_collection(point))
            if form['collection_code'] not in COLLECTION_MAP:
                raise ValueError('草稿集合不存在')
            encoded = json.dumps(content, ensure_ascii=False, sort_keys=True)
            if old:
                if old['source_question_id'] != source_id or old['base_revision'] != base_revision:
                    raise RuntimeError('不能改变草稿的原题版本')
                if (old['revision'] == expected + 1 and old['content_json'] == encoded
                        and old['position_mode'] == position_mode and old['target_order_revision'] == target_order_revision):
                    return self._draft(old)
                if old['revision'] != expected:
                    raise RuntimeError('草稿已更新，请重新打开草稿箱')
            elif expected != 0:
                raise RuntimeError('草稿版本已失效，请重新打开草稿箱')
            elif source_id and conn.execute('SELECT 1 FROM drafts WHERE source_question_id=?', (source_id,)).fetchone():
                raise RuntimeError('此题已有草稿，请从草稿箱继续编辑')
            if source_id and not base_revision:
                raise ValueError('编辑草稿缺少原题版本')
            for ref in image_references(form):
                asset_path(DATA_DIR, ref, require_file=False)
            now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
            source_collection = old['source_collection_code'] if old else (original[0] if original else form['collection_code'])
            conn.execute("""INSERT INTO drafts(id,bank_id,source_question_id,source_collection_code,base_revision,content_json,revision,created_at,updated_at,position_mode,target_order_revision)
                VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET content_json=excluded.content_json,
                revision=excluded.revision,updated_at=excluded.updated_at,position_mode=excluded.position_mode,
                target_order_revision=excluded.target_order_revision""",
                (draft_id, resolved_bank, source_id, source_collection, base_revision, encoded, expected+1, now, now, position_mode, target_order_revision))
            return self._draft(conn.execute('SELECT * FROM drafts WHERE id=?', (draft_id,)).fetchone())

    def discard_draft(self,draft_id,expected):
        with self.transaction() as conn:
            row=conn.execute('SELECT revision FROM drafts WHERE id=?',(draft_id,)).fetchone()
            if not row or row[0]!=expected: raise RuntimeError('草稿版本已改变，请刷新草稿箱')
            conn.execute('INSERT INTO closed_drafts VALUES(?,?,NULL)',(draft_id,expected)); conn.execute('DELETE FROM drafts WHERE id=?',(draft_id,))
    def published_draft(self,draft_id,expected,as_new):
        with closing(self.connect()) as conn:
            row=conn.execute('SELECT * FROM closed_drafts WHERE id=?',(draft_id,)).fetchone()
            if row:
                result=json.loads(row['result_json']) if row['result_json'] else None
                if row['revision']!=expected or not result or result['as_new']!=as_new: raise RuntimeError('草稿已关闭')
                return result
        return None
    def publish_draft(self,draft_id,expected,data,as_new):
        data = dict(data)
        with ASSET_LOCK, self.transaction() as conn:
            closed=conn.execute('SELECT * FROM closed_drafts WHERE id=?',(draft_id,)).fetchone()
            if closed:
                result=json.loads(closed['result_json']) if closed['result_json'] else None
                if not result or closed['revision']!=expected or result['as_new']!=as_new: raise RuntimeError('草稿已关闭')
                return result,False
            row=conn.execute('SELECT * FROM drafts WHERE id=?',(draft_id,)).fetchone()
            if not row or row['revision']!=expected: raise RuntimeError('编译期间草稿已变化，请重新校验并保存')
            if data.get('bank_id', row['bank_id']) != row['bank_id']:
                raise ValueError('草稿不属于当前题库')
            data['bank_id'] = row['bank_id']
            source_collection=row['source_collection_code'] or data.get('collection_code',DEFAULT_COLLECTION)
            affected = {data.get('collection_code') or source_collection}
            if row['source_question_id'] and not as_new:
                old=conn.execute('SELECT * FROM questions WHERE id=?',(row['source_question_id'],)).fetchone()
                if not old: raise RuntimeError('原题已删除；草稿已保留，可另存为新题')
                affected.add(old['collection_code'])
                same_point = data.get('collection_code') == old['collection_code'] and data['point_code'] == old['point_code']
                mode = row['position_mode'] or ('keep' if same_point else 'move')
                data.update(position_mode=mode, target_order_revision=row['target_order_revision'])
                if mode == 'move':
                    self._check_position(conn, data, require=True)
                revision,question=self.update_question(row['source_question_id'],row['base_revision'],data,conn)
            else:
                data['collection_code']=data.get('collection_code') or source_collection
                if as_new and row['position_mode'] in (None, 'keep'):
                    data['position'] = len(self._ids_for_point(conn, data['collection_code'], data['point_code'], bank_id=data['bank_id'])) + 1
                if row['position_mode'] == 'move':
                    data['target_order_revision'] = row['target_order_revision']
                    self._check_position(conn, data, require=True)
                revision,question=self.create_question(data,conn)
            result={'catalog_revision':revision,'question':question,'as_new':as_new,'affected_collections': sorted(affected)}; conn.execute('INSERT INTO closed_drafts VALUES(?,?,?)',(draft_id,expected,json.dumps(result,ensure_ascii=False))); conn.execute('DELETE FROM drafts WHERE id=?',(draft_id,)); return result,True

    def search(self,query,collection_code=None,bank_id=SYSTEM_BANK_ID):
        if collection_code is not None and collection_code not in COLLECTION_MAP:
            raise ValueError('题库集合不存在')
        needle=query.strip().casefold()
        if not needle:return []
        point_titles={(c,pc):(tt,pt) for c,_,_,_,topics in COLLECTIONS for tc,tt,points in topics for pc,pt in points}
        results=[]
        questions = self.ordered_snapshot_all(bank_id)
        if collection_code:
            questions = [q for q in questions if q['collection_code'] == collection_code]
        names = {b['id']: b['name'] for b in self.list_banks()}
        for q in questions:
            fields=[q['question_tex'],*q['options'],q['id'],q['legacy_uid'] or '',str(q['position']),TYPE_NAMES[q['type']]]
            origins=q['sources'].get('origins',[]) if isinstance(q['sources'],dict) else []
            for origin in origins:
                fields.extend([str(origin.get('title') or origin.get('paper_id') or ''),str(origin.get('original_number') or '')] if isinstance(origin,dict) else [str(origin)])
            matched=next((text for text in fields if needle in text.casefold()),None)
            if matched is None:continue
            index=matched.casefold().index(needle); start=max(0,index-30); ct,pt=point_titles[(q['collection_code'],q['point_code'])]
            meta=COLLECTION_MAP[q['collection_code']]; results.append({'id':q['id'],'bank_id':q['bank_id'],'bank_name':names[q['bank_id']],'local_number':q['position'],'type':q['type'],'type_name':TYPE_NAMES[q['type']],'collection_code':q['collection_code'],'collection_title':meta[1],'topic_code':next(tc for tc,_,ps in meta[4] if any(pc==q['point_code'] for pc,_ in ps)),'topic_title':ct,'point_code':q['point_code'],'point_title':pt,'snippet':('…' if start else '')+matched[start:index+len(needle)+70]})
        return results
    def ordered_snapshot_all(self, bank_id=SYSTEM_BANK_ID):
        banks = [bank_id] if bank_id is not None else [b['id'] for b in self.list_banks()]
        rows=[]
        for bank in banks:
            for code,_,_,_,_ in COLLECTIONS:
                rows.extend(self.ordered_snapshot(code,bank)[1])
        return rows

    @staticmethod
    def _pool_items(conn, bank_id=SYSTEM_BANK_ID):
        rows = conn.execute('''SELECT p.added_order,q.*,k.order_revision FROM paper_pool p JOIN questions q ON q.id=p.question_id
            JOIN knowledge_points k ON k.bank_id=q.bank_id AND k.collection_code=q.collection_code AND k.code=q.point_code
            WHERE p.bank_id=? AND q.bank_id=p.bank_id ORDER BY p.added_order''', (bank_id,)).fetchall()
        return [{**CatalogDB._row_to_question(row), 'added_order': row['added_order'],
                 'preview': _plain_preview(row['question_tex'])} for row in rows]

    def pool_items(self, bank_id=SYSTEM_BANK_ID):
        with closing(self.connect()) as conn:
            return self._pool_items(conn, bank_id)

    def pool_add(self, question_id, bank_id=SYSTEM_BANK_ID):
        with self.transaction() as conn:
            if not conn.execute('SELECT 1 FROM questions WHERE id=? AND bank_id=?', (question_id, bank_id)).fetchone():
                raise KeyError('题目不存在')
            if not conn.execute('SELECT 1 FROM paper_pool WHERE question_id=?', (question_id,)).fetchone():
                if conn.execute('SELECT COUNT(*) FROM paper_pool WHERE bank_id=?', (bank_id,)).fetchone()[0] >= 100:
                    raise ValueError('组卷区最多保存 100 道题目')
                conn.execute('INSERT INTO paper_pool(bank_id,question_id) VALUES(?,?)', (bank_id,question_id))
            return self._pool_items(conn, bank_id)

    def pool_remove(self, question_ids, bank_id=SYSTEM_BANK_ID):
        ids = list(question_ids)
        if not ids or len(ids) != len(set(ids)):
            raise ValueError('请选择不重复的组卷区题目')
        with self.transaction() as conn:
            rows = conn.execute('SELECT added_order,question_id FROM paper_pool WHERE bank_id=? ORDER BY added_order', (bank_id,)).fetchall()
            members = {row['question_id']: row['added_order'] for row in rows}
            if any(qid not in members for qid in ids):
                raise ValueError('所选题目不在组卷区')
            removed = [{'question_id': qid, 'added_order': members[qid]} for qid in ids]
            for qid in ids:
                conn.execute('DELETE FROM paper_pool WHERE question_id=?', (qid,))
            conn.execute('INSERT INTO paper_pool_undo(bank_id,singleton,removed_json,created_at) VALUES(?,1,?,?) '
                         'ON CONFLICT(bank_id) DO UPDATE SET removed_json=excluded.removed_json,created_at=excluded.created_at',
                         (bank_id, json.dumps(removed), utc_now()))
            return self._pool_items(conn, bank_id)

    def pool_undo(self, bank_id=SYSTEM_BANK_ID):
        with self.transaction() as conn:
            row = conn.execute('SELECT removed_json FROM paper_pool_undo WHERE bank_id=?', (bank_id,)).fetchone()
            if not row:
                raise ValueError('没有可撤销的移除操作')
            removed = json.loads(row[0])
            available = {r[0] for r in conn.execute('SELECT id FROM questions WHERE bank_id=?', (bank_id,))}
            current = {r[0] for r in conn.execute('SELECT question_id FROM paper_pool WHERE bank_id=?', (bank_id,))}
            restore = [item for item in removed if item['question_id'] in available]
            new_count = sum(item['question_id'] not in current for item in restore)
            if len(current) + new_count > 100:
                raise ValueError('撤销后会超过组卷区 100 题上限，请先移出其他题目')
            for item in restore:
                if item['question_id'] in current:
                    conn.execute('UPDATE paper_pool SET added_order=? WHERE question_id=?',
                                 (item['added_order'], item['question_id']))
                else:
                    conn.execute('INSERT INTO paper_pool(bank_id,added_order,question_id) VALUES(?,?,?)',
                                 (bank_id, item['added_order'], item['question_id']))
            conn.execute('DELETE FROM paper_pool_undo WHERE bank_id=?', (bank_id,))
            return self._pool_items(conn, bank_id)

    def pool_state(self, bank_id=SYSTEM_BANK_ID):
        with closing(self.connect()) as conn:
            items = self._pool_items(conn, bank_id)
            undo = conn.execute('SELECT removed_json FROM paper_pool_undo WHERE bank_id=?', (bank_id,)).fetchone()
            return {'items': items, 'count': len(items), 'limit': 100,
                    'can_undo': bool(undo), 'undo_count': len(json.loads(undo[0])) if undo else 0}

    def paper_snapshot(self, mode, question_ids=None, count=None, bank_id=SYSTEM_BANK_ID):
        with ASSET_LOCK:
            return self._paper_snapshot(mode, question_ids, count, bank_id)

    def paper_render_snapshot(self, mode, question_ids=None, count=None, bank_id=SYSTEM_BANK_ID):
        with ASSET_LOCK:
            snapshot, assets = self._paper_snapshot(mode, question_ids, count, bank_id)
            return snapshot, assets, (RESOURCES/'preamble.tex').read_bytes()

    def _paper_snapshot(self, mode, question_ids=None, count=None, bank_id=SYSTEM_BANK_ID):
        with closing(self.connect()) as conn:
            conn.execute('BEGIN')
            items = self._pool_items(conn, bank_id)
            members = {item['id']: item for item in items}
            if mode == 'manual':
                ids = list(question_ids or [])
                if not 1 <= len(ids) <= 20 or len(ids) != len(set(ids)):
                    raise ValueError('每套训练卷请选择 1 至 20 道不重复题目')
                if any(qid not in members for qid in ids):
                    raise ValueError('存在不在组卷区或已删除的题目')
                wanted = set(ids)
                selected = [item for item in items if item['id'] in wanted]
            elif mode == 'random':
                if not isinstance(count, int) or not 1 <= count <= min(20, len(items)):
                    raise ValueError(f'随机题数须为 1 至 {min(20, len(items))} 道')
                selected = random.SystemRandom().sample(items, count)
            else:
                raise ValueError('未知组卷方式')
            points = {(row['collection_code'], row['code']): row for row in conn.execute('''
                SELECT p.collection_code,p.code,p.title AS point_title,t.title AS topic_title
                FROM knowledge_points p JOIN topics t ON t.bank_id=p.bank_id AND t.collection_code=p.collection_code AND t.code=p.topic_code WHERE p.bank_id=?''', (bank_id,))}
            snapshot = []
            assets = {}
            for item in selected:
                point = points[item['collection_code'], item['point_code']]
                question = {**item, 'collection_title': COLLECTION_MAP[item['collection_code']][1],
                            'topic_title': point['topic_title'], 'point_title': point['point_title']}
                snapshot.append(question)
                for ref in image_references(question):
                    assets[ref] = asset_path(DATA_DIR, ref).read_bytes()
            return snapshot, assets

    @staticmethod
    def asset_digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
