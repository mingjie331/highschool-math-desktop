"""Staging and immutable release publication driven by one collection manifest."""
import argparse,json,os,shutil,zipfile,subprocess
from pathlib import Path
try:
    from install_inventory import sha,package_version
except ModuleNotFoundError:
    from scripts.install_inventory import sha,package_version

ROOT=Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/'scripts/release-manifest.json').read_text('utf-8'))
PKG=json.loads((ROOT/'package.json').read_text('utf-8'))
VERSION=PKG['version'];PRODUCT=PKG['productName']
STAGE=ROOT/'build/release-stage'/VERSION
APP=ROOT/'build/apps'/VERSION/(PRODUCT+'-win32-x64')

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def metadata(file):return {'filename':file.name,'bytes':file.stat().st_size,'sha256':sha(file)}

def check_versions():
    if json.loads((ROOT/'frontend/package.json').read_text('utf-8'))['version']!=VERSION:raise ValueError('Frontend version mismatch')
    if package_version(APP)!=VERSION:raise ValueError('Electron package version mismatch')
    if sha(ROOT/'resources/seed/question_bank.sqlite3')!=CONFIG['seed_sha256']:raise ValueError('Seed changed')
    for doc in CONFIG['documents']:
        if doc['source']=='docs/第三方组件说明.md':continue
        if VERSION not in (ROOT/doc['source']).read_text('utf-8'):raise ValueError('Current document lacks current version: '+doc['source'])

def build_windows():
    check_versions();STAGE.mkdir(parents=True,exist_ok=True)
    files=[]
    for file in sorted(APP.rglob('*')):
        if not file.is_file() or file.name=='app-files.json':continue
        relative=file.relative_to(APP)
        if relative.parts[0].lower() in CONFIG['protected_directories'] or file.name.endswith('.credentials.enc'):raise ValueError('Personal data in build application')
        files.append({'path':relative.as_posix(),'bytes':file.stat().st_size,'sha256':sha(file)})
    write_json(APP/'app-files.json',{'format_version':1,'version':VERSION,'schema':8,'product':PRODUCT,'files':files})
    target=STAGE/f'{PRODUCT}-{VERSION}-Windows-x64.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for file in sorted(APP.rglob('*')):
            if file.is_file():archive.write(file,Path(PRODUCT)/file.relative_to(APP))
    return target

def build_source():
    STAGE.mkdir(parents=True,exist_ok=True);target=STAGE/f'{PRODUCT}-{VERSION}-源码.zip'
    excluded=set(CONFIG['source_excluded'])
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name in CONFIG['source_directories']:
            for file in sorted((ROOT/name).rglob('*')):
                relative=file.relative_to(ROOT)
                excluded_path=any(relative.as_posix()==p or relative.as_posix().startswith(p+'/') for p in CONFIG.get('source_excluded_paths',[]))
                private_file=file.name.startswith('.env') or '.credentials.enc' in file.name or file.name.lower() in {'.npmrc','.pypirc'} or file.suffix.lower() in {'.pem','.key','.p12','.pfx','.db','.log','.tmp'}
                private_db=('.sqlite3' in file.name.lower() or file.suffix.lower()=='.sqlite') and relative.as_posix()!='resources/seed/question_bank.sqlite3'
                if not file.is_file() or set(relative.parts)&excluded or excluded_path or private_file or private_db or file.name.endswith(('.pyc','-wal','-shm','.tsbuildinfo')):continue
                archive.write(file,Path('question-desktop')/relative)
        for name in CONFIG['source_files']:archive.write(ROOT/name,Path('question-desktop')/name)
    return target

def stage_manifests():
    windows=STAGE/f'{PRODUCT}-{VERSION}-Windows-x64.zip';source=STAGE/f'{PRODUCT}-{VERSION}-源码.zip'
    w,s=metadata(windows),metadata(source)
    write_json(STAGE/f'checksums-{VERSION}.json',{'filename':w['filename'],'filename_sha256':w['sha256'],'bytes':w['bytes'],'source':s})
    write_json(STAGE/'release.json',{'format_version':1,'version':VERSION,'schema':8,'artifacts':{'windows':w,'source':s},
          'program_manifest':'高中数学题库/app-files.json','validation':CONFIG['validation_directory'].replace('{version}',VERSION),
          'seed_sha256':CONFIG['seed_sha256'],'protected_directories':CONFIG['protected_directories']})
    (STAGE/'发行说明.md').write_text(f'# 高中数学题库 {VERSION}\n\n固定使用目录、文档归位、不可覆盖发行与本地更新。schema 8；识别模型、提示词及数学内容保持。\n\n更新请保持 Windows ZIP、release.json 和校验清单位于同一目录，双击固定安装目录的“本地更新”。\n',encoding='utf-8')

def verify(directory):
    directory=Path(directory);release=json.loads((directory/'release.json').read_text('utf-8'))
    for artifact in release['artifacts'].values():
        file=directory/artifact['filename']
        if sha(file)!=artifact['sha256'] or file.stat().st_size!=artifact['bytes']:raise ValueError('Artifact hash mismatch')
        with zipfile.ZipFile(file) as archive:
            if archive.testzip():raise ValueError('ZIP CRC failure')
            for name in archive.namelist():
                parts=Path(name).parts
                if len(parts)>1 and parts[1] in {'data','.cache','.local','output','logs','runtime','test-results'} or name.endswith('.credentials.enc'):raise ValueError('Private runtime data in release')
    return release

def publish():
    destination=ROOT/'release'/VERSION
    if destination.exists():raise FileExistsError('Immutable release already exists; choose a new version: '+VERSION)
    stage_manifests();verify(STAGE)
    temporary=ROOT/'release'/('.publishing-'+VERSION)
    if temporary.exists():raise FileExistsError('Previous publication staging exists; inspect it before retry')
    temporary.mkdir(parents=True)
    for name in [f'{PRODUCT}-{VERSION}-Windows-x64.zip',f'{PRODUCT}-{VERSION}-源码.zip',f'checksums-{VERSION}.json','release.json','发行说明.md']:
        shutil.copy2(STAGE/name,temporary/name)
    verify(temporary);temporary.rename(destination)
    print('IMMUTABLE_RELEASE='+str(destination))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--publish',action='store_true');parser.add_argument('--verify');parser.add_argument('--manifests',action='store_true');args=parser.parse_args()
    if args.publish:publish()
    elif args.verify:print(json.dumps(verify(args.verify),ensure_ascii=False))
    elif args.manifests:stage_manifests()
    else:print(build_windows());print(build_source());stage_manifests()
