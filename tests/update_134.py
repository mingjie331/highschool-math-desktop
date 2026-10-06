"""Exercise the shipped PowerShell updater with real versioned executables."""
import json,os,shutil,subprocess,sys,zipfile,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from install_inventory import sha,PROTECTED
AREA=ROOT/'test-results/update-134';AREA.mkdir(parents=True,exist_ok=True);OUT=Path(tempfile.mkdtemp(dir=AREA,prefix='run-'))
sys.path.insert(0,str(ROOT))
from tests.private_paths import OLD_APP
SOURCE=OLD_APP
if SOURCE is None:raise SystemExit('Provide --old-app or QD_TEST_OLD_APP (isolated test copies only)')
PACKAGE=ROOT/'build/release-stage/1.3.4/高中数学题库-1.3.4-Windows-x64.zip'
SCRIPT=ROOT/'scripts/update_app.ps1';checks=[]

def fixture(name):
    home=OUT/name
    if home.exists():raise FileExistsError('Test home exists; preserve previous evidence')
    home.mkdir()
    for p in SOURCE.iterdir():
        if p.name in PROTECTED or p.name=='app-files.json':continue
        if p.is_dir():shutil.copytree(p,home/p.name)
        else:shutil.copy2(p,home/p.name)
    for n in PROTECTED:(home/n).mkdir(exist_ok=True)
    for n in PROTECTED:(home/n/'preserve.txt').write_text('protected-'+n,encoding='utf-8')
    (home/'unknown-note.txt').write_text('unknown file must survive',encoding='utf-8')
    files=[{'path':p.relative_to(home).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in home.rglob('*') if p.is_file() and p.relative_to(home).parts[0] not in PROTECTED and p.name!='unknown-note.txt']
    (home/'app-files.json').write_text(json.dumps({'version':'1.3.3','schema':8,'files':files},ensure_ascii=False),encoding='utf-8')
    return home

def run(home,package=PACKAGE,fail=0,timeout=360):
    result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(SCRIPT),'-Worker','-Target',str(home),'-BackupRoot',str(OUT/'backups'),'-Package',str(package),'-TestFailAfter',str(fail)],capture_output=True,timeout=timeout)
    return result.returncode,result.stdout.decode('utf-8',errors='replace')+result.stderr.decode('utf-8',errors='replace')

def snapshot(home):return {p.relative_to(home).as_posix():sha(p) for p in home.rglob('*') if p.is_file()}
def record(name,condition,details=None):
    if not condition:raise AssertionError(name+': '+str(details))
    checks.append({'name':name,'passed':True});print(json.dumps(checks[-1]),flush=True)

try:
    home=fixture('success');protected={n:sha(home/n/'preserve.txt') for n in PROTECTED}
    code,text=run(home);record('update_success_preserves_config_data_and_unknown_files',code==0 and 'UPDATE_COMPLETE=1.3.4' in text,text[-1600:])
    record('protected_dirs_unchanged',all(sha(home/n/'preserve.txt')==h for n,h in protected.items()) and (home/'unknown-note.txt').read_text('utf-8')=='unknown file must survive')
    before=snapshot(home);code,text=run(home);record('repeat_update_is_noop',code==0 and 'ALREADY_CURRENT=1.3.4' in text and snapshot(home)==before,text[-1000:])
    changed=home/'README.md';changed.write_text('different same-version program',encoding='utf-8');before=snapshot(home)
    code,text=run(home);record('same_version_different_content_rejected',code!=0 and snapshot(home)==before,text[-1000:])
    rollback=fixture('rollback');before=snapshot(rollback);code,text=run(rollback,fail=3)
    record('injected_write_failure_rolls_back_entire_program',code!=0 and snapshot(rollback)==before,text[-1000:])
    broken=OUT/'corrupt-package';broken.mkdir();shutil.copy2(PACKAGE.parent/'release.json',broken/'release.json');shutil.copy2(PACKAGE.parent/'checksums-1.3.4.json',broken/'checksums-1.3.4.json');(broken/PACKAGE.name).write_bytes(b'broken ZIP')
    before=snapshot(rollback);code,text=run(rollback,broken/PACKAGE.name);record('corrupt_zip_rejected_without_writes',code!=0 and snapshot(rollback)==before,text[-1000:])
    # Even a checksummed ZIP must reject traversal before extraction or close.
    unsafe=OUT/'unsafe-package';unsafe.mkdir();file=unsafe/PACKAGE.name
    with zipfile.ZipFile(PACKAGE) as src,zipfile.ZipFile(file,'w',compression=zipfile.ZIP_DEFLATED) as dst:
        for entry in src.infolist():dst.writestr(entry,src.read(entry.filename))
        dst.writestr('高中数学题库/../outside.txt','escape')
    release=json.loads((PACKAGE.parent/'release.json').read_text('utf-8'));release['artifacts']['windows'].update(bytes=file.stat().st_size,sha256=sha(file))
    (unsafe/'release.json').write_text(json.dumps(release,ensure_ascii=False),encoding='utf-8')
    checksum=json.loads((PACKAGE.parent/'checksums-1.3.4.json').read_text('utf-8'));checksum.update(bytes=file.stat().st_size,filename_sha256=sha(file));(unsafe/'checksums-1.3.4.json').write_text(json.dumps(checksum,ensure_ascii=False),encoding='utf-8')
    before=snapshot(rollback);code,text=run(rollback,file);record('checksummed_traversal_rejected',code!=0 and snapshot(rollback)==before and not (OUT/'outside.txt').exists(),text[-1000:])
except Exception as error:
    checks.append({'name':'failure','passed':False,'error':str(error)});raise
finally:(AREA/'results.json').write_text(json.dumps({'paid_calls':0,'checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
