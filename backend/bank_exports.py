"""Frozen, independent exports for a bank and an explicit selection scope."""
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid
from urllib.parse import quote

from . import latex_service as latex
from .assets import ASSET_LOCK, image_references, asset_path
from .catalog import DATA_DIR, COLLECTION_MAP
from .render_archive import staged_archive, resource_hashes
from .runtime import RESOURCES
from .tex_layout import RENDER_VERSION


def safe_name(value):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:100] or '题库'


class BankExports:
    def __init__(self, db):
        self.db=db;self.lock=threading.RLock();self.states={};self.threads=[];self.stopping=False

    def stop(self):
        self.stopping=True

    def specification(self, bank_id, collection_code, scope=None):
        catalog=self.db.catalog(bank_id)
        collection=next((c for c in catalog['collections'] if c['code']==collection_code),None)
        if not collection:raise ValueError('学期不存在')
        scope=scope or {'kind':'semester'};kind=scope.get('kind','semester')
        normalized={'kind':kind}
        if kind=='topic':
            if not any(t['code']==scope.get('topic_code') for t in collection['topics']):raise ValueError('专题不存在')
            normalized['topic_code']=scope['topic_code']
        elif kind=='point':
            if not any(p['code']==scope.get('point_code') for t in collection['topics'] for p in t['points']):raise ValueError('考点不存在')
            normalized['point_code']=scope['point_code']
        elif kind=='selected':
            ids=scope.get('question_ids',[])
            valid={q['id'] for t in collection['topics'] for p in t['points'] for q in p['questions']}
            if not ids or len(ids)!=len(set(ids)) or not set(ids)<=valid:raise ValueError('请仅选择当前题库和学期的题目')
            normalized['question_ids']=sorted(ids)
        elif kind!='semester':raise ValueError('导出范围无效')
        spec={'bank_id':bank_id,'collection_code':collection_code,'scope':normalized}
        key=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:32]
        return key,spec,catalog,collection

    def folder(self, key):
        if not re.fullmatch('[0-9a-f]{32}',key):raise ValueError('导出标识无效')
        root=latex.EXPORT_DIR/'banks'/key
        try:
            gen=json.loads((root/'current.json').read_text('utf-8'))['generation']
            if not re.fullmatch('book-[0-9a-f]{32}',gen):return None
            folder=root/'versions'/gen
            manifest=json.loads((folder/'export_manifest.json').read_text('utf-8'))
            if manifest['key']!=key:return None
            for name in manifest['files'].values():
                if Path(name).name!=name or not (folder/name).is_file():return None
            return folder
        except (OSError,ValueError,KeyError,TypeError):return None

    def selected(self, spec, questions, collection):
        scope=spec['scope'];kind=scope['kind']
        if kind=='semester':return questions
        if kind=='selected':return [q for q in questions if q['id'] in set(scope['question_ids'])]
        points={p['code'] for t in collection['topics'] if kind!='topic' or t['code']==scope['topic_code'] for p in t['points']}
        if kind=='point':points={scope['point_code']}
        return [q for q in questions if q['point_code'] in points]

    def status(self,bank_id,collection_code,scope=None):
        key,spec,catalog,collection=self.specification(bank_id,collection_code,scope)
        revision,questions=self.db.ordered_snapshot(collection_code,bank_id)
        count=len(self.selected(spec,questions,collection))
        with self.lock:state=dict(self.states.get(key,{'state':'idle','message':'尚未生成','error':None}))
        folder=self.folder(key);manifest=json.loads((folder/'export_manifest.json').read_text('utf-8')) if folder else {}
        names=manifest.get('files',{})
        return {**state,**spec,'key':key,'collection_title':collection['title'],'bank_name':catalog['bank_name'],'current_count':count,
                'available':bool(folder),'stale':not folder or manifest.get('collection_revision')!=revision or manifest.get('bank_name')!=catalog['bank_name'] or manifest.get('render_version')!=RENDER_VERSION,
                'count':manifest.get('count',0),'updated_at':manifest.get('generated_at'),'collection_revision':manifest.get('collection_revision'),
                'question_filename':names.get('question','题目册.pdf'),'solution_filename':names.get('solution','解析册.pdf'),
                'question_pdf':f'/api/bank-exports/{key}/files/question','solution_pdf':f'/api/bank-exports/{key}/files/solution'}

    def schedule(self,bank_id,collection_code,scope=None):
        key,spec,catalog,collection=self.specification(bank_id,collection_code,scope)
        with ASSET_LOCK:
            revision,questions=self.db.ordered_snapshot(collection_code,bank_id)
            questions=self.selected(spec,questions,collection)
            if not questions:raise ValueError('当前范围没有题目')
            assets={ref:asset_path(DATA_DIR,ref).read_bytes() for q in questions for ref in image_references(q)}
            preamble=(RESOURCES/'preamble.tex').read_bytes()
        with self.lock:
            if self.stopping:raise RuntimeError('应用正在退出')
            if self.states.get(key,{}).get('state') not in {'pending','building'}:
                self.states[key]={'state':'pending','message':'已固定题目快照，等待编译','error':None}
                thread=threading.Thread(target=self.run,args=(key,spec,catalog,collection,revision,questions,assets,preamble),daemon=True)
                self.threads.append(thread);thread.start()
        return self.status(bank_id,collection_code,scope)

    def run(self,key,spec,catalog,collection,revision,questions,assets,preamble):
        try:
            with self.lock:self.states[key]={'state':'building','message':'正在编译题目册和解析册','error':None}
            generation='book-'+uuid.uuid4().hex;root=latex.EXPORT_DIR/'banks'/key
            scope=spec['scope'];label={'semester':'全学期','topic':'专题-'+scope.get('topic_code',''),'point':'考点-'+scope.get('point_code',''),'selected':'勾选题目'}[scope['kind']]
            prefix=safe_name(catalog['bank_name']+'_'+collection['title']+'_'+label)
            names={'question':prefix+'_题目册.pdf','solution':prefix+'_解析册.pdf'}
            with staged_archive(root/'versions'/generation,assets,preamble) as stage:
                qt,manifest=latex.full_document(questions,False,spec['collection_code'],asset_root=stage,include_empty=False)
                st,_=latex.full_document(questions,True,spec['collection_code'],asset_root=stage,include_empty=False)
                caption=latex.escape_text(catalog['bank_name']+' / '+collection['title']+' / '+label)
                override='\\renewcommand{\\collectiontitle}{'+caption+'}\n\\begin{document}'
                qt=qt.replace('\\begin{document}',override,1);st=st.replace('\\begin{document}',override,1)
                for kind,tex in [('question',qt),('solution',st)]:
                    if self.stopping:raise RuntimeError('应用正在退出')
                    (stage/names[kind]).write_bytes(latex.compile_tex(tex,'bank-'+kind,timeout=600,passes=2,resource_root=stage,priority=2))
                    (stage/('questions.tex' if kind=='question' else 'solutions.tex')).write_text(tex,'utf-8')
                metadata={**spec,'key':key,'bank_name':catalog['bank_name'],'collection_revision':revision,'generation':generation,
                          'count':len(questions),'files':names,'questions':manifest,'generated_at':latex._stamp(),'render_version':RENDER_VERSION,**resource_hashes(assets,preamble)}
                (stage/'export_manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),'utf-8')
            if self.stopping:raise RuntimeError('应用正在退出')
            temp=root/('current-'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps({'generation':generation}),'utf-8');os.replace(temp,root/'current.json')
            with self.lock:self.states[key]={'state':'ready','message':'导出完成','error':None}
        except Exception as error:
            with self.lock:self.states[key]={'state':'failed','message':'导出失败，已保留上次成功版本','error':str(error)}
