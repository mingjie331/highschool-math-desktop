"""Opt-in validation using real XeLaTeX and completely isolated data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument('--output', default=str(ROOT/'test-results/real-latex'))
args = parser.parse_args()
OUTPUT = Path(args.output).resolve()
OUTPUT.mkdir(parents=True, exist_ok=True)
HOME = Path(tempfile.mkdtemp(prefix='run-', dir=OUTPUT))
RESOURCES = HOME/'resources'
shutil.copytree(ROOT/'resources/seed', RESOURCES/'seed')
shutil.copy2(ROOT/'resources/preamble.tex', RESOURCES/'preamble.tex')
os.environ['QD_HOME'] = str(HOME)
os.environ['QD_RESOURCES'] = str(RESOURCES)
os.environ['QD_FRONTEND'] = str(ROOT/'frontend/dist')
os.environ['QD_TOKEN'] = 'real-validation'
os.environ.pop('QUESTION_VIEWER_SKIP_LATEX_VALIDATION', None)

from backend.runtime import initialize_seed
initialize_seed()
from backend.app import app, db, exports, papers
from backend.assets import image_references
from backend.latex_service import compile_tex, active_export_dir, ExportManager
from backend.papers import active_paper_dir
from fastapi.testclient import TestClient
from pypdf import PdfReader

checks = []
def check(name, condition, details=None):
    item={'name':name, 'passed':bool(condition), 'details':details}
    checks.append(item)
    print(json.dumps(item,ensure_ascii=False),flush=True)
    if not condition:raise AssertionError(name)

def wait_status(manager, code=None):
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        state=manager.status(code) if code else manager.status()
        if state['state'] not in ('pending','building'):return state
        time.sleep(.2)
    raise TimeoutError('编译任务超时')

try:
    seed_hash=hashlib.sha256((ROOT/'resources/seed/question_bank.sqlite3').read_bytes()).hexdigest()
    with TestClient(app,headers={'x-desktop-token':'real-validation'}) as client:
        check('seed_migration_counts', {c['code']:c['count'] for c in db.catalog()['collections']} ==
              {'gaoyi-first':518,'gaoyi-second':0,'gaokao-first':0,'gaokao-second':0,'misc':109})
        check('token_required',client.get('/api/health',headers={'x-desktop-token':'wrong'}).status_code==403)
        response=client.post('/api/desktop/latex/test')
        check('real_latex_environment',response.status_code==200,response.text)
        for qtype in ['single','multi','fill','long']:
            value={'type':qtype,'question_tex':r'计算 $1+1$。','solution_tex':r'由加法知 $1+1=2$。',
                   'answer_tex':'AB' if qtype=='multi' else 'A' if qtype=='single' else '2',
                   'options':['$1$','$2$','$3$','$4$'] if qtype in ('single','multi') else [],'sources':{}}
            for view in ['question','solution']:
                response=client.post('/api/preview',json={**value,'view':view})
                check('preview_'+qtype+'_'+view,response.status_code==200 and response.content.startswith(b'%PDF-'),len(response.content))
        value={'collection_code':'gaoyi-second','point_code':'6.1','position':1,'type':'fill',
               'question_tex':r'$1+1=$？','solution_tex':r'$1+1=2$。','answer_tex':'2','options':[],'sources':{}}
        response=client.post('/api/questions',json=value)
        check('real_validated_save',response.status_code==201,response.text)
        question=response.json()['question']
        check('real_delete',client.delete('/api/questions/'+question['id'],params={'revision':question['revision']}).status_code==200)

        # Freeze an uploaded resource and template, then remove both originals.
        image=next((HOME/'data/assets').glob('*.png')).read_bytes()
        upload=client.post('/api/assets',files={'file':('真实图.png',image,'image/png')})
        check('real_upload',upload.status_code==201)
        relative=upload.json()['latex_path']
        _,question=db.create_question({**value,'question_tex':r'图：\includegraphics[width=2cm]{'+relative+'}'})
        frozen=db.collection_snapshot('gaoyi-second')
        _,removed=db.delete_question(question['id'],question['revision']);db.cleanup_assets(removed)
        template=RESOURCES/'preamble.tex';preamble=template.read_bytes();template.unlink()
        isolated=ExportManager(db)
        try:isolated._run_export('gaoyi-second',frozen)
        finally:template.write_bytes(preamble)
        check('real_frozen_export_after_deletion',isolated.status('gaoyi-second')['available'] and isolated.status('gaoyi-second')['state']!='failed',isolated.status('gaoyi-second'))

        for code in ['misc','gaoyi-first']:
            started=time.perf_counter();exports.schedule(code);state=wait_status(exports,code)
            check('full_export_'+code,state['state']=='ready',{'seconds':round(time.perf_counter()-started,2),'error':state.get('error')})
            folder=active_export_dir(code)
            manifest=json.loads((folder/'export_manifest.json').read_text('utf-8'))
            for file in folder.glob('*.pdf'):
                reader=PdfReader(file);text='\n'.join(page.extract_text() for page in reader.pages)
                numbers=[int(n) for n in re.findall(r'第\s*(\d+)\s*题\s*(?:单选|多选|填空|解答)',text)]
                check('numbering_'+file.name,numbers==list(range(1,manifest['count']+1)),{'pages':len(reader.pages),'count':len(numbers)})
                if code=='misc' and '题目册' in file.name:
                    check('no_blank_terminal_page',len(reader.pages[-1].extract_text().strip())>80,reader.pages[-1].extract_text()[-200:])
            check('archive_hashes_'+code,all(hashlib.sha256((folder/name).read_bytes()).hexdigest()==digest for name,digest in manifest['assets'].items()))

        baseline=db.ordered_snapshot_all();first=baseline[0];image_q=next(q for q in baseline if image_references(q))
        db.pool_add(first['id']);db.pool_add(image_q['id'])
        papers.schedule('manual',[image_q['id'],first['id']]);state=wait_status(papers)
        check('image_training_paper',state['state']=='ready',state)
        folder=active_paper_dir();portable=HOME/'independent-source';shutil.copytree(folder,portable)
        with (portable/'questions.tex').open(encoding='utf-8') as source:
            pdf=compile_tex(source.read(),'independent',passes=2,resource_root=portable)
        (portable/'independent.pdf').write_bytes(pdf)
        check('independent_recompile',len(PdfReader(portable/'independent.pdf').pages)>=2)
        manifest=json.loads((folder/'paper_manifest.json').read_text('utf-8'))
        check('manual_order_and_training_hashes',manifest['questions'][0]['id']==first['id'] and bool(manifest['assets']))
        check('seed_unchanged',seed_hash==hashlib.sha256((ROOT/'resources/seed/question_bank.sqlite3').read_bytes()).hexdigest(),seed_hash)
finally:
    (OUTPUT/'results.json').write_text(json.dumps({'home':str(HOME),'checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
print('REAL_VALIDATION_HOME='+str(HOME),flush=True)
