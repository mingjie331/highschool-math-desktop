"""Verify schema-eight upgrade on a private isolated copy, never on the source."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys

parser=argparse.ArgumentParser()
parser.add_argument('--source',required=True,help='Existing application home; read-only')
parser.add_argument('--output',required=True,help='New isolated test directory')
args=parser.parse_args()
source=Path(args.source).resolve();output=Path(args.output).resolve()
if output.exists() or output==source or source.is_relative_to(output):raise SystemExit('Use a new distinct isolated output directory')
output.mkdir(parents=True)
target=output/'data/question_bank.sqlite3';target.parent.mkdir()
original=source/'data/question_bank.sqlite3'
with closing(sqlite3.connect(original.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(target)) as dst:
    src.backup(dst)
with closing(sqlite3.connect(target)) as conn:
    tables={name:[dict(zip([c[1] for c in conn.execute('PRAGMA table_info("'+name+'")')],row)) for row in conn.execute('SELECT * FROM "'+name+'"')]
            for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
os.environ['QD_HOME']=str(output)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.catalog import CatalogDB
db=CatalogDB(target);db.initialize()
with closing(sqlite3.connect(target)) as conn:
    conn.row_factory=sqlite3.Row
    for name,rows in tables.items():
        if name=='metadata':continue
        cols=list(rows[0]) if rows else []
        actual=[{key:row[key] for key in cols} for row in conn.execute('SELECT * FROM "'+name+'"')]
        sort=lambda values:sorted(json.dumps(v,sort_keys=True,ensure_ascii=False) for v in values)
        assert sort(actual)==sort(rows),'Changed existing records in '+name
    assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert not conn.execute('PRAGMA foreign_key_check').fetchall()
    assert conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]=='9'
count=db.catalog()['total'];assert count==len(tables['questions'])
assert db.list_banks()[0]['name']=='系统题库'
before=target.stat().st_size;db.initialize();assert target.stat().st_size==before
report={'passed':True,'questions':count,'drafts':len(tables.get('drafts',[])),'existing_tables_preserved':len(tables)-1,'integrity':'ok','schema':9,'idempotent':True}
(output/'upgrade-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
