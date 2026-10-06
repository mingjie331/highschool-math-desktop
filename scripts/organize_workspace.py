"""One-time, verified relocation. No database merge or directory deletion."""
import argparse,json,shutil,zipfile
from pathlib import Path
try:
    from install_inventory import sha,package_version,tree_inventory
except ModuleNotFoundError:
    from scripts.install_inventory import sha,package_version,tree_inventory

ROOT=Path(__file__).resolve().parents[1]
BACKUP=ROOT/'.local/backups/maintenance-1.3.4'
REPORTS={
 '1.0.4':['项目审查报告.md','project-audit-results.json'],
 '1.0.5':['修复与验证记录.md','fix-validation-results.json'],
 '1.1.0':['AI录题使用与验证.md','agent-validation-results.json'],
 '1.2.0':['PDF录题修复与验证.md','pdf-import-validation-results.json','PDF录题逐题检查.csv'],
 '1.3.0':['工作台改造与验证.md','workbench-validation-results.json'],
 '1.3.1':['核对工作台修复与验证.md','review-guidance-validation-results.json'],
 '1.3.2':['录题与排版修复验证.md','import-132-validation-results.json'],
 '1.3.3':['滚动布局与题源验证.md','ui-133-validation-results.json']}

def move(source,target,records):
    if not source.exists():return
    if target.exists():raise ValueError('Destination exists: '+str(target))
    source=source.resolve();target=target.resolve()
    if not source.is_relative_to(ROOT) or not target.is_relative_to(ROOT) or source==target:raise ValueError('Relocation outside workspace')
    before=tree_inventory(source) if source.is_dir() else {'sha256':sha(source)}
    BACKUP.mkdir(parents=True,exist_ok=True)
    journal=BACKUP/'relocation-journal.jsonl'
    with journal.open('a',encoding='utf-8') as output:output.write(json.dumps({'phase':'before','from':str(source),'to':str(target),'inventory':before},ensure_ascii=False)+'\n')
    target.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(source),str(target))
    after=tree_inventory(target) if target.is_dir() else {'sha256':sha(target)}
    with journal.open('a',encoding='utf-8') as output:output.write(json.dumps({'phase':'after','from':str(source),'to':str(target),'verified':before==after,'inventory':after},ensure_ascii=False)+'\n')
    if before!=after:raise ValueError('Relocation verification failed: '+str(target))
    records.append({'from':str(source),'to':str(target),'verified':True,'inventory':before})

def organize():
    BACKUP.mkdir(parents=True,exist_ok=True);records=[];historical=[]
    for file in sorted((ROOT/'release').glob('checksums-*.json')):
        version=file.stem.removeprefix('checksums-');value=json.loads(file.read_text('utf-8'));target=ROOT/'release'/version
        for artifact in [value,value.get('source',{})]:
            if not artifact:continue
            path=ROOT/'release'/artifact['filename']
            if sha(path)!=artifact['sha256'] or path.stat().st_size!=artifact['bytes']:raise ValueError('Historical checksum mismatch')
            with zipfile.ZipFile(path) as archive:
                if archive.testzip():raise ValueError('Historical ZIP damaged')
            move(path,target/path.name,records)
        move(file,target/file.name,records)
        release={'format_version':1,'version':version,'historical_reorganization':True,
                 'artifacts':{'windows':{k:value[k] for k in ['filename','bytes','sha256']},'source':value.get('source')},
                 'note':'Original archives and checksums unchanged; extracted folders are not historical release snapshots.'}
        (target/'release.json').write_text(json.dumps(release,ensure_ascii=False,indent=2),encoding='utf-8')
        (target/'发行说明.md').write_text(f'# 历史发行 {version}\n\n原 ZIP 和校验清单字节保持，已核验 CRC 与 SHA-256。本目录只保存发行文件，旧解压目录验收后转入本机恢复备份。\n',encoding='utf-8')
        historical.append(release)
    for version,files in REPORTS.items():
        for name in files:move(ROOT/name,ROOT/'docs/validation'/version/name,records)
    original=BACKUP/'original-documents';original.mkdir(exist_ok=True)
    for old,new in [('THIRD_PARTY.md','第三方组件说明.md'),('交接说明.md','开发交接.md')]:
        source=ROOT/old
        if source.exists():
            if not (original/old).exists():shutil.copy2(source,original/old)
            move(source,ROOT/'docs'/new,records)
    if (ROOT/'README.md').exists() and not (original/'README.md').exists():shutil.copy2(ROOT/'README.md',original/'README.md')
    move(ROOT/'测试题目',ROOT/'.local/test-materials',records)
    updates={'import-132','review-131','ui-133'}
    snapshots={'agent-120-live','legacy-120','legacy-130'}
    for name in updates:move(ROOT/'.cache'/name,ROOT/'.local/backups/updates/legacy'/name,records)
    for name in snapshots:move(ROOT/'.cache'/name,ROOT/'.local/backups/test-snapshots'/name,records)
    for name in ['agent-release-acceptance','release-acceptance-1.0.5','release-verification','release-verification-final','agent-baseline','fix-baseline','pdf-plan-inspection']:
        move(ROOT/'.cache'/name,ROOT/'test-results/legacy-cache'/name,records)
    for file in sorted((ROOT/'release').glob('*/release.json')):
        value=json.loads(file.read_text('utf-8'))
        if value.get('historical_reorganization') and not any(v['version']==value['version'] for v in historical):historical.append(value)
    (BACKUP/'relocations.json').write_text(json.dumps({'records':records,'history':historical,'remaining_cache_policy':'Unknown files retained; no blanket cleanup'},ensure_ascii=False,indent=2),encoding='utf-8')
    mapping=[{'from':r['from'],'to':r['to'],'verified':True} for r in records]
    directory=ROOT/'docs/validation/1.3.4';directory.mkdir(parents=True,exist_ok=True)
    (directory/'relocation-index.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Verified relocations:',len(records))

def archive_apps():
    # Run only after the fixed installation was accepted. Preserve every old tree.
    proof=BACKUP/'fixed-install-accepted.json'
    if not proof.exists() or not json.loads(proof.read_text('utf-8')).get('accepted'):raise ValueError('Fixed-install acceptance required')
    if not list((ROOT/'release').glob('*/高中数学题库-win32-x64')):
        print('Old application directories already archived; original catalog retained.');return
    records=[];catalog=[]
    for directory in sorted((ROOT/'release').glob('*/高中数学题库-win32-x64')):
        actual=package_version(directory);has_data=(directory/'data/question_bank.sqlite3').is_file()
        target=ROOT/'.local/backups/legacy-apps/maintenance-1.3.4'/f'folder-{directory.parent.name}--actual-{actual}'
        catalog.append({'original_home':str(directory),'archive_home':str(target),'actual_version':actual,'contains_user_database':has_data,
                        'classification':'Recovery copy, not a historical release snapshot'})
        move(directory,target,records)
    (BACKUP/'legacy-apps.json').write_text(json.dumps({'apps':catalog,'records':records},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Archived verified old application trees:',len(catalog))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--archive-apps',action='store_true');args=parser.parse_args()
    archive_apps() if args.archive_apps else organize()
