"""Question-number indexing and per-question extraction, shared by PDF and photos."""
import base64
import io
import re
from pathlib import Path
from .agent_models import Candidate,Region,Figure,SolveResult
from .agent_store import encode
from .deepseek import ProviderError,AgentCancelled


def parse_numbers(text):
    if not text or not text.strip():return []
    value=text.strip().replace('，',',').replace('、',',').replace('；',',').replace(';',',')
    value=re.sub(r'[–—~～至到]', '-',value)
    result=[]
    for token in value.split(','):
        token=token.strip()
        if not re.fullmatch(r'\d{1,3}(?:\s*-\s*\d{1,3})?',token):raise ValueError('提取题号请使用 19、1,3,19 或 17–19')
        bounds=[int(n) for n in token.split('-')];a=bounds[0];b=bounds[-1]
        if not 1<=a<=b<=999 or b-a>=50:raise ValueError('题号范围无效或超过 50 道题')
        result.extend(str(n) for n in range(a,b+1))
    result=list(dict.fromkeys(result))
    if len(result)>50:raise ValueError('每批最多 50 道题')
    return result


def natural_numbers(instruction):
    def convert(match):
        digits={'零':0,'〇':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
        total=0;digit=0
        for char in match[0]:
            if char in digits:digit=digits[char]
            else:total+=(digit or 1)*(100 if char=='百' else 10);digit=0
        return str(total+digit)
    instruction=re.sub(r'[零〇一二两三四五六七八九十百]+',convert,instruction)
    numbers=[]
    for match in re.finditer(r'第\s*(\d{1,3}(?:\s*[-–—至到、,，]\s*\d{1,3})*)\s*题',instruction):numbers+=parse_numbers(match[1])
    return list(dict.fromkeys(numbers))


def pair_key(filename):
    return re.sub(r'[_\s+＋-]*(?:试卷|答案|解析)$','',Path(filename).stem).strip()


def answer_document(filename):
    return bool(re.search(r'(?:答案|解析)\.pdf$',filename,re.I)) and '试卷' not in filename


def named_documents(text,documents):
    direct=[did for did,d in documents.items() if d['filename'] in text or Path(d['filename']).stem in text]
    if direct:return direct
    import difflib
    named=[]
    for did,d in documents.items():
        match=difflib.SequenceMatcher(None,text,Path(d['filename']).stem).find_longest_match()
        if match.size>=4:named.append(did)
    return named


def resolve_selection(manager,payload):
    payload=dict(payload);pages=[manager.store.attachment(a) for a in payload['attachment_ids']]
    numbers=parse_numbers(payload.get('question_numbers',''));natural=natural_numbers(payload.get('instruction',''))
    if numbers and natural and set(numbers)!=set(natural):raise ValueError('提取题号与识别要求不一致，请重新确认')
    payload['selected_numbers']=numbers or natural
    documents={p['document_id']:manager.store.document(p['document_id']) for p in pages if p.get('document_id')}
    pairs=payload.get('document_pairs')
    if pairs is None:
        pairs=[]
        for did,d in documents.items():
            if answer_document(d['filename']):
                peers=[q for q in documents.values() if q['id']!=did and pair_key(q['filename'])==pair_key(d['filename']) and not answer_document(q['filename'])]
                if len(peers)==1:pairs.append({'question_document_id':peers[0]['id'],'answer_document_id':did})
    grouping={};used=set()
    for pair in pairs:
        q,a=pair['question_document_id'],pair['answer_document_id']
        if q==a:raise ValueError('文件不能与自身配对：'+documents.get(q,{}).get('filename',q)+'；含试卷和答案的同一文件请选择不配对')
        if q not in documents or a not in documents:raise ValueError('配对双方都需选择页面，请检查所选试卷及答案文件')
        if a in used or q in used:raise ValueError('文件被重复配对：'+documents[q]['filename']+' / '+documents[a]['filename'])
        grouping[q]=q;grouping[a]=q;used.update([q,a])
    for did in documents:grouping.setdefault(did,did)
    target=payload.get('target_document_id')
    text=payload.get('instruction','')
    named=named_documents(text,documents)
    if target and target not in documents:raise ValueError('指定文件不在本批所选 PDF 中')
    if target and named and any(grouping[n]!=grouping[target] for n in named):raise ValueError('指定文件与识别要求不一致，请重新确认')
    if not target and named:
        if len({grouping[n] for n in named})!=1:raise ValueError('指令匹配多个 PDF，请选择目标文件')
        target=named[0]
    groups=set(grouping.values())|({'images'} if any(not p.get('document_id') for p in pages) else set())
    if payload['selected_numbers'] and not target and len(groups)>1:raise ValueError('多个试卷可能包含同号题，请选择要提取的 PDF 文件')
    payload.update(resolved_target=grouping.get(target),document_groups=grouping,resolved_pairs=pairs)
    return payload


def page_views(manager,aid,regions=None):
    info=manager.store.attachment(aid)
    rectangles=[r['rect'] for r in (regions or []) if r['image_id']==aid] or [[0,0,1,1]]
    if rectangles==[[0,0,1,1]] and info['width']>info['height']*1.2:rectangles=[[0,0,.5,1],[.5,0,1,1]]
    blocks=[];mapping={}
    for rect in rectangles:
        alias='view-'+str(len(blocks)+1);im=manager._crop({'image_id':aid,'rect':rect})
        # Index needs readable numbering; detailed extraction uses native crops.
        im.thumbnail((2400,2800))
        from PIL import ImageDraw
        draw=ImageDraw.Draw(im)
        for n in range(1,20):
            y=int(im.height*n/20);x=int(im.width*n/20)
            draw.line((0,y,im.width,y),fill=(180,210,235),width=1);draw.text((2,y+2),f'y={n/20:.2f}',fill=(30,90,150))
            draw.line((x,0,x,im.height),fill=(215,225,240),width=1);draw.text((x+2,2),f'{n/20:.2f}',fill=(30,90,150))
        buf=io.BytesIO();im.save(buf,'JPEG',quality=92)
        blocks.append({'type':'text','text':alias})
        blocks.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode(),'detail':'original'}})
        mapping[alias]={'image_id':aid,'rect':rect}
    return blocks,mapping


async def index_and_extract(manager,tid,cancel,failure_ids=None):
    task=manager.store.task(tid);payload=task['payload'];checkpoint=payload.get('question_checkpoint',{})
    index=checkpoint.get('index',[]);cursor=checkpoint.get('page_cursor',0);item_ids=checkpoint.get('item_ids',[])
    failed=checkpoint.get('failures',{})
    item_ids=[i for i in item_ids if manager.get_item(i)['state']!='deleted']
    def save():
        with manager._lock:
            latest=manager.store.task(tid)['payload'];current=latest.get('question_checkpoint',{});deleted=current.get('deleted_keys',[])
            live=[i for i in item_ids if manager.get_item(i)['state']!='deleted']
            kept={k:v for k,v in checkpoint.get('completed',{}).items() if k not in deleted and manager.get_item(v)['state']!='deleted'}
            latest['question_checkpoint']={**checkpoint,'index':index,'page_cursor':cursor,'item_ids':live,'completed':kept,'failures':failed,'deleted_keys':deleted}
            manager.store.task_update(tid,payload_json=encode(latest))
    for aid in payload['attachment_ids'][cursor:]:
        if cancel.is_set():raise AgentCancelled('任务已取消')
        info=manager.store.attachment(aid);blocks,mapping=page_views(manager,aid,payload.get('input_regions'))
        prompt=('只建立高中数学试卷/答案的题号与区域索引，不转写题目或解题。页面可能多栏、有跨页延续，按阅读顺序。'
            '返回 json {"segments":[{"number":"19","role":"question或answer或solution","regions":[{"image_id":"view-1","rect":[左,上,右,下]}],'
            '"figures":[{"id":"图标识","image_id":"view-1","rect":[左,上,右,下],"field":"question_tex或solution_tex"}],"uncertain":false}]}。'
            '坐标必须对应当前 view、为0到1；区域包住完整正文、选项及所有配图，每个题号单独列出。'
            '浅蓝网格只是坐标参照，不是题目；参考 y 标注定位原题号和结束选项，不要将下一题区域错归上一题。'
            '答案表按题号分别列出，解析里的题号不要当新题干。续题归到正确原题号，编号无法确定时 number 为空、uncertain=true。'
            '必须标出所有数学配图，不能把文本/表格当几何图。不要将答题纸空白、页码或分值作为题目。')
        context={'filename':info['filename'],'page':info['page_number'],'previous_segments':index[-3:]}
        value,_=await manager.provider.json([{'role':'system','content':prompt},{'role':'user','content':[{'type':'text','text':encode(context)},*blocks]}],
            cancel=cancel,usage_callback=lambda u:manager.store.account_call(tid,u),max_tokens=12000)
        segments=value.get('segments')
        if not isinstance(segments,list) or len(segments)>80:raise ValueError('题号索引格式无效，请调整页面范围')
        new=[]
        for segment in segments:
            number=str(segment.get('number','')).strip();role=segment.get('role','question')
            if role not in {'question','answer','solution'} or number and not re.fullmatch(r'\d{1,3}',number):raise ValueError('题号索引格式无效')
            regions=[{**manager._map_region(r,mapping),'role':role} for r in segment.get('regions',[])]
            if not regions:raise ValueError('题号索引缺少原图区域')
            figures=[{**manager._map_region(f,mapping),'id':str(f.get('id','figure')),'field':f.get('field','question_tex' if role=='question' else 'solution_tex')} for f in segment.get('figures',[])]
            group=payload.get('document_groups',{}).get(info.get('document_id'),'images')
            new.append({'number':number,'role':role,'regions':regions,'figures':figures,'uncertain':bool(segment.get('uncertain')),'group':group})
        index.extend(new);cursor+=1;save()
        manager.store.task_update(tid,message=f'已定位 {cursor}/{len(payload["attachment_ids"])} 页的题号与配图')
    entries={}
    for segment in index:
        if payload.get('resolved_target') and segment['group']!=payload['resolved_target']:continue
        if payload.get('selected_numbers') and segment['number'] not in payload['selected_numbers']:continue
        key=segment['group']+':'+segment['number']
        entries.setdefault(key,[]).append(segment)
    complete=checkpoint.get('completed',{})
    found=set()
    for key,parts in entries.items():
        number=parts[0]['number'];found.add(number)
        with manager._lock:deleted=manager.store.task(tid)['payload'].get('question_checkpoint',{}).get('deleted_keys',[])
        if key in complete or key in deleted:continue
        if failure_ids is not None and key not in failure_ids:continue
        if not any(p['role']=='question' for p in parts):
            failed[key]={'id':key,'original_number':number,'regions':[r for p in parts for r in p['regions']],'stage':'recognition','code':'missing_stem_region','message':'仅找到答案／解析，请补选同题题干区域'};save();continue
        if len(complete)>=50:raise ValueError('每批最多 50 道题，请拆批；已识别草稿保留')
        regions=[r for p in parts for r in p['regions']]
        figures=[f for p in parts for f in p['figures']]
        manager.store.task_update(tid,message=f'正在提取第 {number or "未明确题号"} 题')
        try:
            candidate=await extract_one(manager,tid,number,regions,figures,cancel)
            if any(p['uncertain'] for p in parts):candidate['uncertainties'].append('题目边界或题号不清，请对照原页核对')
            iid=manager.accept_candidates(tid,[candidate])[0];item_ids.append(iid);complete[key]=iid
            failed.pop(key,None);checkpoint['completed']=complete;save()
        except (ProviderError,ValueError) as exc:
            if isinstance(exc,ProviderError) and (exc.status in {401,402,403,429} or exc.code=='budget_exhausted'):raise
            detail=exc.detail('recognition') if isinstance(exc,ProviderError) else {'stage':'recognition','code':'candidate_invalid','message':str(exc)[:500]}
            failed[key]={'id':key,'original_number':number,'regions':regions,**detail};save()
    missing=set(payload.get('selected_numbers',[]))-found
    if missing:raise ValueError('未找到指定题号：'+','.join(sorted(missing,key=int))+'；已识别候选题保留，请核对文件与页码')
    if not item_ids and not failed:raise ValueError('未找到完整题干。若仅上传答案，请补充同套试卷并配对')
    checkpoint.update(complete=True,completed=complete);save()
    return [i for i in item_ids if manager.get_item(i)['state']!='deleted']


async def extract_one(manager,tid,number,regions,figures,cancel):
    task=manager.store.task(tid)
    unique=[]
    for figure in figures:
        x,y,r,b=figure['rect'];same=None
        for peer in unique:
            a,c,d,e=peer['rect'];intersection=max(0,min(r,d)-max(x,a))*max(0,min(b,e)-max(y,c))
            if peer['image_id']==figure['image_id'] and peer['field']==figure['field'] and intersection/max(1e-9,min((r-x)*(b-y),(d-a)*(e-c)))>.5:same=peer;break
        if same:
            a,c,d,e=same['rect'];same['rect']=[min(x,a),min(y,c),max(r,d),max(b,e)]
        else:unique.append(dict(figure))
    figures=unique
    # Vision coordinates are approximate. OCR sees complete source columns so a
    # shifted index box cannot silently remove a condition or borrow a neighbour.
    # Keep provenance broad and editable instead of trusting a tight guessed box.
    contexts=[]
    for region in regions:
        page=manager.store.attachment(region['image_id']);x,y,r,b=region['rect']
        if page['width']>page['height']*1.2:
            rect=[0,0,.5,1] if (x+r)/2<.5 else [.5,0,1,1]
        else:rect=[0,0,1,1]
        boundaries=[r['rect'] for r in (task['payload'].get('input_regions') or []) if r['image_id']==region['image_id']]
        if boundaries:
            for boundary in boundaries:
                clipped=[max(rect[0],boundary[0]),max(rect[1],boundary[1]),min(rect[2],boundary[2]),min(rect[3],boundary[3])]
                # Only boundaries overlapping this indexed segment belong to it.
                if min(region['rect'][2],boundary[2])<=max(region['rect'][0],boundary[0]) or min(region['rect'][3],boundary[3])<=max(region['rect'][1],boundary[1]):continue
                if clipped[0]<clipped[2] and clipped[1]<clipped[3]:
                    value={**region,'rect':clipped}
                    if value not in contexts:contexts.append(value)
        else:
            value={**region,'rect':rect}
            if value not in contexts:contexts.append(value)
    regions=contexts
    schema=Candidate.model_json_schema()
    system=('只提取这一道高中数学题及其原答案解析，不解题、不补缺失内容。输出一个 json 题目对象，schema 就是顶层结构，不使用 questions、question 或数组包装，严格匹配 schema。'
        '保留原条件、选项、符号、全部解答步骤及配图；不要加原题号和分值到题干正文。不要输出宏定义、文件路径或 includegraphics。'
        'answer_tex 只写简短答案/结论；solution_tex 必须转写原解析的完整步骤。即使原稿只写“解”，解题过程也必须放 solution_tex，不能把全文都放 answer_tex。'
        '配图使用 [FIGURE:id] 和 figures，题干图、解析图分别保留。所有 regions 和 figures 只能引用本次发送的 view 标识，坐标0到1。'
        '跨块重复不重复转写，看不清写 uncertainties。可见原内容 origin=original，缺失=missing。只使用提供的分类目录。'
        'JSON 字符串内 LaTeX 反斜线按 JSON 转义一次；分式分母与括号层级严格按原图。'
        '原页包含多题，original_number 必须来自图上题号。只转写指定题号，不能把相邻题的条件/选项借来，也不能将指定数字套在别的题上。'
        '\nschema='+encode(schema)+'\n分类目录='+encode(manager.taxonomy()))
    # At most two smaller retries; truncated JSON is never accepted.
    for attempt in range(3):
        requests=[None] if attempt==0 else ['question','solution']
        try:
            candidate=None
            for part in requests:
                subset=regions if part is None else [r for r in regions if (r.get('role','question')=='question')==(part=='question')]
                if not subset:continue
                views,aliases=manager._visual_blocks(task,subset)
                content=[{'type':'text','text':encode({'original_number':number,'part':part or 'complete','instruction':'只提取原题号 '+number+'。答案表可能包含其他题，仅取第 '+number+' 题对应的答案；禁止返回其他题号。',
                    'region_roles':[r.get('role','question') for r in subset],'expected_figure_count':len(figures)})}]
                for block in views:content.extend([{'type':'text','text':block['alias']},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+block['data'],'detail':'original'}}])
                value,_=await manager.provider.json([{'role':'system','content':system},{'role':'user','content':content}],
                    cancel=cancel,usage_callback=lambda u:manager.store.account_call(tid,u),max_tokens=16000 if attempt<2 else 32000)
                questions=value.get('questions')
                if questions is None and 'question_tex' in value:questions=[value]
                if questions is None and isinstance(value.get('question'),dict):questions=[value['question']]
                if questions is None and isinstance(value.get(number),dict):questions=[value[number]]
                if isinstance(questions,dict):questions=[questions]
                if isinstance(questions,list):
                    import os,json
                    diagnostic=os.environ.get('QD_AI_DIAGNOSTIC_DIR')
                    if diagnostic:
                        path=Path(diagnostic);path.mkdir(parents=True,exist_ok=True)
                        with (path/'envelopes.jsonl').open('a',encoding='utf-8') as file:
                            file.write(json.dumps({'target':number,'part':part,'top_keys':list(value)[:30],'items':[{'number':str(q.get('original_number',''))[:40],'keys':list(q)[:30],
                                'stem_length':len(str(q.get('question_tex',''))),'solution_length':len(str(q.get('solution_tex','')))} for q in questions if isinstance(q,dict)]},ensure_ascii=False)+'\n')
                if isinstance(questions,list) and len(questions)>1:
                    questions=[q for q in questions if re.search(r'\d{1,3}',str(q.get('original_number',''))) and re.search(r'\d{1,3}',str(q.get('original_number','')))[0]==number]
                if not isinstance(questions,list) or len(questions)!=1:raise ValueError('指定区域未返回唯一完整题目，请核对题目边界')
                raw=questions[0]
                controlled={key:raw[key] for key in Candidate.model_fields if key in raw}
                # Source regions are server-owned context. The model's guessed
                # boxes cannot remove pages or introduce a foreign source.
                controlled['regions']=regions
                current=Candidate.model_validate(controlled).model_dump()
                observed_match=re.search(r'\d{1,3}',current['original_number']);observed=observed_match[0] if observed_match else ''
                if observed and number and observed!=number:raise ValueError('所识别的原题号与目标不一致，请核对页面区域')
                current['regions']=regions
                current['figures']=[{**f,**manager._map_region(f,aliases)} for f in current['figures']]
                if candidate is None:candidate=current
                else:
                    for field in ['answer_tex','solution_tex','answer_origin','solution_origin']:
                        if current.get(field):candidate[field]=current[field]
                    candidate['uncertainties']+=current['uncertainties'];candidate['figures']+=current['figures']
            if candidate is None:raise ValueError('题目区域为空')
            candidate['original_number']=number or candidate['original_number'];candidate['expected_figures']=len(figures)
            candidate['question_tex']=re.sub(r'^\s*'+re.escape(number)+r'[.．、]\s*(?:[（(]\d+\s*分[）)]\s*)?','',candidate['question_tex']) if number else candidate['question_tex']
            inline=list(re.finditer(r'(?:^|\n)\s*([ABCD])[.．、]\s*',candidate['question_tex']))
            if len(inline)==4 and [m[1] for m in inline]==list('ABCD'):
                original=candidate['question_tex']
                options=[original[m.end():inline[i+1].start() if i<3 else len(original)].strip() for i,m in enumerate(inline)]
                candidate['question_tex']=original[:inline[0].start()].strip()
                if len(candidate['options'])!=4:candidate['options']=options
                if candidate['type'] not in {'single','multi'}:
                    letters=re.sub(r'[^ABCD]','',candidate['answer_tex'])
                    candidate['type']='multi' if len(set(letters))>1 else 'single'
            if any(r.get('role')=='solution' for r in regions) and not candidate['solution_tex'].strip():
                if len(candidate['answer_tex'])>150:
                    candidate['solution_tex']=candidate['answer_tex'];candidate['solution_origin']='original';candidate['answer_tex']='';candidate['answer_origin']='missing'
                else:
                    candidate['uncertainties'].append('原解析区域已定位，但完整步骤未提取，请重新识别此题')
            # Recover indexed figures and union overlapping boxes so an extraction
            # rectangle cannot cut off labels found by the page index.
            for indexed in figures:
                x,y,r,b=indexed['rect']
                matches=[f for f in candidate['figures'] if f['image_id']==indexed['image_id'] and f['field']==indexed['field']
                    and min(f['rect'][2],r)>max(f['rect'][0],x) and min(f['rect'][3],b)>max(f['rect'][1],y)]
                if matches:
                    found=matches[0];a,c,d,e=found['rect'];found['rect']=[min(a,x),min(c,y),max(d,r),max(e,b)]
                else:candidate['figures'].append({**indexed,'id':'indexed-'+str(len(candidate['figures'])+1)})
            # Different partial responses may reuse figure IDs.
            seen=set()
            for i,figure in enumerate(candidate['figures']):
                if figure['id'] in seen:
                    replacement='part-'+str(i+1);field=figure['field']
                    candidate[field]=candidate[field].replace('[FIGURE:'+figure['id']+']','[FIGURE:'+replacement+']',1)
                    figure['id']=replacement
                seen.add(figure['id'])
            # Prefer all indexed original regions, not the model's incomplete provenance.
            if len(candidate['figures'])<len(figures):
                candidate['uncertainties'].append('提取配图数量少于页面索引，请对照题干和解析补齐配图')
            from .tex_layout import has_stem
            if not has_stem(candidate['question_tex']):raise ValueError('未识别到有效题干')
            markers={f['id'] for f in candidate['figures']}
            for field in ['question_tex','answer_tex','solution_tex']:
                def unmatched(match):
                    if match[1] in markers:return match[0]
                    candidate['uncertainties'].append('配图标记 '+match[1]+' 未匹配，请对照原图补充配图');candidate['expected_figures']=max(candidate['expected_figures'],len(markers)+1)
                    return ''
                candidate[field]=re.sub(r'\[FIGURE:([^]]+)\]',unmatched,candidate[field])
            return candidate
        except ProviderError as exc:
            if exc.code not in {'output_truncated','invalid_json'} or attempt==2:raise
    raise ValueError('提取未完成')


async def extract_original_solution(manager,tid,number,stem,regions,cancel,missing_parts=None):
    selected=[r for r in regions if r.get('role') in {'answer','solution'}]
    blocks,_=manager._visual_blocks(manager.store.task(tid),selected)
    content=[{'type':'text','text':encode({'original_number':number,'question':stem[:2000],
        'instruction':'仅转写缺少的子问 '+','.join(sorted(missing_parts,key=int))+'，保留子问编号，不重复其他子问' if missing_parts else '转写完整原解析'})}]
    for block in blocks:content.extend([{'type':'text','text':block['alias']},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+block['data'],'detail':'original'}}])
    for attempt in range(2):
        value,_=await manager.provider.json([{'role':'system','content':'只转写提供图片中的指定题号原解析，不解题、不补写或改变数学步骤。返回 json {"answer_tex":"简短原结论","solution_tex":"完整原解析文字及公式","uncertainties":[]}。可能跨页，逐步保留。不要返回题干、分类、图片坐标、宏定义或文件路径。图形由本地另行保留，不输出图形标记。模糊内容标注 uncertainties。'},
            {'role':'user','content':content}],cancel=cancel,usage_callback=lambda u:manager.store.account_call(tid,u),max_tokens=32000)
        result=SolveResult.model_validate(value).model_dump()
        if result['solution_tex'].strip() or attempt==1:return result
    return result
