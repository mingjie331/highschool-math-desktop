"""Initial fixed-directory migration. Original installation remains recoverable."""
import argparse,datetime,json,shutil,uuid
from pathlib import Path
try:
    from install_inventory import inventory,consistent_copy,filesystem_path,sha,PROTECTED
except ModuleNotFoundError:
    from scripts.install_inventory import inventory,consistent_copy,filesystem_path,sha,PROTECTED

def migrate(source,target,backup_root):
    source=Path(source).resolve();target=Path(target).resolve();backup_root=Path(backup_root).resolve()
    if source==target or target.is_relative_to(source) or source.is_relative_to(target):raise ValueError('Distinct, non-nested migration paths required')
    if target.exists():raise FileExistsError('Target already exists. Back it up and explicitly choose the intended dataset; no overwrite performed.')
    if backup_root.is_relative_to(source) or backup_root.is_relative_to(target):raise ValueError('Backup root must be outside both application homes')
    import subprocess
    command="$wanted='"+str(source).replace("'","''")+"';@(Get-CimInstance Win32_Process -Filter \"Name='高中数学题库.exe' OR Name='question-backend.exe'\" | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($wanted+'\\',[StringComparison]::OrdinalIgnoreCase) }).Count"
    processes=subprocess.check_output(['powershell.exe','-NoProfile','-Command',command],encoding='utf-8').strip()
    if processes!='0':raise RuntimeError('Source is running. Exit normally and save drafts before migration; no forced termination.')
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
    backup=backup_root/'migrations'/stamp;backup.mkdir(parents=True)
    before=inventory(source)
    (backup/'source-inventory.json').write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
    snapshot=backup/'original-home'
    shutil.copytree(filesystem_path(source),filesystem_path(snapshot))
    if inventory(snapshot)['files']!=before['files']:raise ValueError('Full original-home copy does not match source')
    target.parent.mkdir(parents=True,exist_ok=True);stage=target.parent/('.question-bank-migration-'+stamp)
    if stage.exists():raise FileExistsError('Unexpected migration staging directory')
    shutil.copytree(filesystem_path(source),filesystem_path(stage))
    # Preserve the raw DB/WAL in the original backup; install a consistent DB.
    db=stage/'data/question_bank.sqlite3';temp=db.with_name('question_bank.consistent.sqlite3')
    consistent_copy(source/'data/question_bank.sqlite3',temp)
    temp.replace(db)
    for name in ['question_bank.sqlite3-wal','question_bank.sqlite3-shm']:
        file=stage/'data'/name
        assert file.resolve().is_relative_to(stage.resolve())
        file.unlink(missing_ok=True)
    after=inventory(stage)
    if before['database']!=after['database']:raise ValueError('Business-table verification failed')
    ignored={'question_bank.sqlite3','question_bank.sqlite3-wal','question_bank.sqlite3-shm'}
    for name in PROTECTED:
        a={k:v for k,v in before['files'][name].items() if name!='data' or k not in ignored}
        b={k:v for k,v in after['files'][name].items() if name!='data' or k not in ignored}
        if a!=b:raise ValueError('Protected-tree verification failed: '+name)
    program=[]
    for file in stage.rglob('*'):
        if file.is_file() and file.relative_to(stage).parts[0] not in PROTECTED and (len(file.relative_to(stage).parts)==1 or file.relative_to(stage).parts[0] in {'resources','locales','docs','tools'}):
            program.append({'path':file.relative_to(stage).as_posix(),'bytes':file.stat().st_size,'sha256':sha(file)})
    (stage/'app-files.json').write_text(json.dumps({'format_version':1,'version':before['version'],'schema':8,'product':'高中数学题库','files':program},ensure_ascii=False,indent=2),encoding='utf-8')
    (stage/'.cache/installation.json').write_text(json.dumps({'backup_root':str(backup_root),'migrated_from':str(source),'migration_backup':str(backup)},ensure_ascii=False,indent=2),encoding='utf-8')
    # Enable only after every pre-launch content/configuration check passed.
    if target.exists():raise FileExistsError('Target appeared during migration; verified staging retained for recovery')
    stage.rename(target)
    result={'source':str(source),'target':str(target),'backup':str(backup),'actual_source_version':before['version'],
            'business_tables_equal':True,'protected_files_equal_before_launch':True,'original_retained':True,'database_method':'SQLite backup, includes WAL'}
    (backup/'migration.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--target',default=r'D:\Apps\高中数学题库');parser.add_argument('--backups',required=True);args=parser.parse_args()
    print(json.dumps(migrate(args.source,args.target,args.backups),ensure_ascii=False))
