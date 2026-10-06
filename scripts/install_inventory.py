"""Read-only application/data inventory and WAL-safe copies. Never log keys."""
import argparse,hashlib,json,sqlite3,struct,os
from contextlib import closing
from pathlib import Path

PROTECTED={'data','.cache','output','logs'}
def filesystem_path(path):
    value=str(Path(path).absolute())
    return Path('\\\\?\\'+value) if os.name=='nt' and not value.startswith('\\\\?\\') else Path(value)

def sha(path):
    h=hashlib.sha256()
    with filesystem_path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def package_version(home):
    file=Path(home)/'resources/app.asar'
    with file.open('rb') as source:
        initial=source.read(16);header_size=struct.unpack_from('<I',initial,4)[0];length=struct.unpack_from('<I',initial,12)[0]
        header=json.loads(source.read(length));entry=header['files']['package.json']
        source.seek(8+header_size+int(entry['offset']));return json.loads(source.read(entry['size']))['version']

def database_inventory(path):
    path=Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as conn:
        conn.execute('BEGIN')
        tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        rows={}
        for table in tables:
            quoted='"'+table.replace('"','""')+'"'
            values=conn.execute('SELECT * FROM '+quoted).fetchall()
            serialized=sorted(json.dumps(list(row),ensure_ascii=False,separators=(',',':'),default=lambda x:x.hex()) for row in values)
            h=hashlib.sha256()
            for row in serialized:h.update(row.encode('utf-8'));h.update(b'\n')
            rows[table]={'count':len(values),'sha256':h.hexdigest()}
        return {'integrity':conn.execute('PRAGMA integrity_check').fetchone()[0],
                'foreign_key_errors':len(conn.execute('PRAGMA foreign_key_check').fetchall()),'tables':rows,
                'schema':dict(conn.execute('SELECT key,value FROM metadata')).get('schema_version')}

def consistent_copy(source,target):
    source=Path(source).resolve();target=Path(target).resolve()
    if source==target or target.exists():raise ValueError('Backup destination must be a new distinct file')
    target.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database backup integrity failed')
    if database_inventory(source)!=database_inventory(target):raise ValueError('Database content changed during copy')
    wal=target.with_name(target.name+'-wal')
    if wal.exists() and wal.stat().st_size!=0:raise ValueError('Unexpected non-empty backup WAL; preserve it for inspection')
    for suffix in ['-wal','-shm']:target.with_name(target.name+suffix).unlink(missing_ok=True)

def tree_inventory(directory):
    directory=filesystem_path(directory);result={}
    if not directory.exists():return result
    for file in sorted(directory.rglob('*')):
        if file.is_symlink():raise ValueError('Unexpected linked file: '+str(file))
        if not file.is_file():continue
        name=file.relative_to(directory).as_posix()
        if file.name.endswith('.credentials.enc'):
            result[name]={'exists':True};continue
        result[name]={'bytes':file.stat().st_size,'sha256':sha(file)}
    return result

def inventory(home):
    home=Path(home).resolve();db=home/'data/question_bank.sqlite3'
    result={'home':str(home),'version':package_version(home),'encrypted_key_exists':(home/'data/deepseek.credentials.enc').is_file(),
            'encryption_context_exists':(home/'.cache/electron/Local State').is_file(),
            'sqlite_files':{n:(home/'data'/n).exists() for n in ['question_bank.sqlite3','question_bank.sqlite3-wal','question_bank.sqlite3-shm']}}
    if db.exists():result['database']=database_inventory(db)
    result['files']={name:tree_inventory(home/name) for name in sorted(PROTECTED)}
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('home');parser.add_argument('--output');parser.add_argument('--backup-database')
    args=parser.parse_args()
    if args.backup_database:consistent_copy(Path(args.home)/'data/question_bank.sqlite3',args.backup_database)
    value=inventory(args.home)
    if args.output:
        file=Path(args.output);file.parent.mkdir(parents=True,exist_ok=True);file.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'version':value['version'],'database':value.get('database',{}).get('tables',{}),'encrypted_key_exists':value['encrypted_key_exists']},ensure_ascii=False))
