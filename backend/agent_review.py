"""Human review authority and compact workbench queries, separate from model tools."""
import copy
import json
import uuid
from contextlib import closing
from .agent_store import encode,now
from .assets import ASSET_LOCK


class ReviewError(RuntimeError):
    def __init__(self,message,code='review_required',issues=None,item_ids=None):
        super().__init__(message);self.detail={'code':code,'message':message,'issues':issues or [],'item_ids':item_ids or []}


def issues(item):
    d=item['details'];f=item['form'];result=[]
    figures={fig['id']:fig for fig in d.get('figures',[])}
    def add(code,section,message,field=None,figure=None,action=None):
        target={'field':field} if field else {}
        if figure:target.update(figure_id=figure['id'],image_id=figure['image_id'],rect=figure['rect'])
        result.append({'code':code,'section':section,'message':message,'field':field,'target':target,'action':action or 'edit'})
    if not f.get('question_tex','').strip():add('missing_stem','stem','题干尚未完整提取','question_tex')
    if f.get('type') in {'single','multi'} and (len(f.get('options',[]))!=4 or any(not o.strip() for o in f['options'])):add('missing_options','stem','需要四个完整选项','options')
    if not f.get('answer_tex','').strip():add('missing_answer','answer','答案缺失','answer_tex')
    if not f.get('solution_tex','').strip():add('missing_solution','answer','解析缺失','solution_tex')
    if not d.get('original_number','').strip():add('missing_number','classification','请补充原题号','original_number')
    origins=f.get('sources',{}).get('origins',[])
    if not any(o.get('title','').strip() for o in origins) and not f.get('sources',{}).get('source_missing'):add('missing_source','classification','填写题源或明确题源暂缺','source_title')
    for index,message in enumerate(d.get('uncertainties',[])):
        section='figures' if '配图' in message else 'classification' if '题号' in message or '分类' in message else 'answer' if '解析' in message or '答案' in message else 'stem'
        add('uncertainty:'+str(index),section,message,action='resolve_uncertainty')
    if d.get('classification_uncertain'):add('classification','classification','分类需要确认','point_code',action='confirm_classification')
    if d.get('answer_conflict'):add('answer_conflict','answer','原答案与 AI 候选存在冲突',action='resolve_answer')
    if len(figures)<d.get('expected_figures',0):add('missing_figures','figures','配图尚未补齐',action='add_figure')
    for index,message in enumerate(d.get('figure_issues',[])):
        figure=next((fig for fid,fig in figures.items() if message.startswith('配图 '+fid+' ')),None)
        add('figure_edge:'+str(index),'figures',message,figure=figure,action='crop_figure')
    if figures and not d.get('figures_confirmed'):add('figure_confirmation','figures','请确认题干图与解析图完整',action='confirm_figures')
    if d.get('duplicates') and not d.get('allow_duplicate'):add('duplicates','stem','发现重复或相似题，请决定跳过或仍新增',action='review_duplicate')
    error=d.get('validation_error')
    # Validation often repeats a specific business problem. Keep the actionable
    # issue instead of showing a second generic warning for the same cause.
    redundant=bool(error and (
        ('配图边缘' in error and d.get('figure_issues')) or
        ('配图未补齐' in error and len(figures)<d.get('expected_figures',0)) or
        ('确认' in error and '配图完整' in error and figures and not d.get('figures_confirmed'))))
    if error and not redundant and not any(error==i['message'] for i in result):
        section='figures' if '配图' in error else 'classification' if '分类' in error else 'answer' if '子问' in error or '解析' in error else 'layout'
        add('validation',section,error,action='validate' if section=='layout' else 'edit')
    return result


def stage(manager,item,worker=False):
    if item['state'] in {'published','skipped','deleted'}:return item['state']
    if worker and item['state'] in {'pending','recognizing','solving','classifying','validating'}:return 'processing'
    from .agent_lifecycle import legacy_failure
    if legacy_failure(item):return 'failed'
    if not item.get('reviewed_hash'):return 'review'
    current=manager._item_hash(item['form'],item['details'])
    if item['state']=='ready' and item.get('reviewed_hash')==current and item.get('validated_hash')==current:return 'publish'
    return 'review'


def queue(manager,task_id=None,source=None,review_stage=None,offset=0,limit=100,bank_id="system"):
    # No attachment images, session history or full candidate content is returned.
    with closing(manager.db.connect()) as conn:
        tasks=[dict(r) for r in conn.execute("SELECT id,session_id,message,state,error,created_at,json_extract(payload_json,'$.attachment_ids') AS attachment_ids,json_extract(payload_json,'$.page_count') AS page_count FROM ai_tasks WHERE session_id IN (SELECT id FROM ai_sessions WHERE bank_id=?) ORDER BY created_at DESC",(bank_id,))]
        rows=conn.execute('''WITH snapshots AS (
            SELECT i.*, d.revision AS draft_revision,
                COALESCE(json_extract(d.content_json,'$.form'),json_extract(c.result_json,'$.question'),'{}') AS form_json
            FROM ai_items i LEFT JOIN drafts d ON d.id=i.draft_id LEFT JOIN closed_drafts c ON c.id=i.draft_id)
            SELECT id,task_id,item_order,revision,state,details_json,question_id,reviewed_hash,reviewed_at,validated_hash,draft_revision,
                json_extract(form_json,'$.id') AS closed_question_id,
                substr(json_extract(form_json,'$.question_tex'),1,180) AS summary,
                json_extract(form_json,'$.type') AS type,json_extract(form_json,'$.collection_code') AS collection_code,
                json_extract(form_json,'$.point_code') AS point_code,
                json_extract(form_json,'$.sources.origins') AS origins,json_extract(form_json,'$.sources.source_missing') AS source_missing,
                length(trim(json_extract(form_json,'$.answer_tex'))) AS answer_length,
                length(trim(json_extract(form_json,'$.solution_tex'))) AS solution_length,
                (SELECT json_group_array(CASE WHEN length(trim(value))>0 THEN 'content' ELSE '' END)
                  FROM json_each(json_extract(form_json,'$.options'))) AS options
            FROM snapshots ORDER BY item_order''').fetchall()
        filenames={r['id']:r['filename'] for r in conn.execute('SELECT id,filename FROM ai_attachments')}
    by_task={t['id']:[] for t in tasks}
    for row in rows:by_task.get(row['task_id'],[]).append(row)
    counts={key:0 for key in ['processing','review','publish','published','skipped','failed','deleted']};output=[];cards=[]
    with manager._lock:working=set(manager._cancel)
    for task in tasks:
        task_counts={key:0 for key in counts};titles=set()
        for row in by_task[task['id']]:
            item=dict(row);iid=item['id'];item['details']=json.loads(item.pop('details_json'))
            if item['draft_revision'] is None and item['state']!='deleted':
                item['state']='published' if item['closed_question_id'] else 'skipped'
                if item['closed_question_id']:item['question_id']=item['closed_question_id']
            item['form']={'question_tex':item['summary'] or '', 'type':item['type'],'collection_code':item['collection_code'],
                'point_code':item['point_code'],'options':json.loads(item['options'] or '[]'),
                'answer_tex':'content' if item['answer_length'] else '', 'solution_tex':'content' if item['solution_length'] else '',
                'sources':{'origins':json.loads(item['origins'] or '[]'),'source_missing':bool(item['source_missing'])}}
            # Only reviewed items need full content/resource hashing to detect
            # stale human approval. Unreviewed queues load summaries alone.
            if item['reviewed_hash'] and item['state'] not in {'published','skipped'}:item=manager.get_item(iid)
            s=stage(manager,item,task['id'] in working);task_counts[s]+=1;counts[s]+=1
            f=item['form'];origins=f.get('sources',{}).get('origins',[]);title='；'.join(o.get('title','') for o in origins);titles.add(title)
            if s in {'failed','deleted'}:continue
            if task_id and task['id']!=task_id or source and source.casefold() not in title.casefold() or review_stage and s!=review_stage:continue
            output.append({'id':iid,'task_id':task['id'],'session_id':task['session_id'],'task_title':task['message'],'item_order':item['item_order'],
                'revision':item['revision'],'state':item['state'],'review_stage':s,'original_number':item['details'].get('original_number',''),
                'summary':f.get('question_tex','')[:180],'type':f.get('type','long'),'collection_code':f.get('collection_code',''),
                'point_code':f.get('point_code',''),'source_title':title,'question_id':item['question_id'],'issues':issues(item) if s=='review' else []})
        ids=json.loads(task.pop('attachment_ids') or '[]');page_count=task.pop('page_count')
        stored=manager.store.task(task['id']);new_failures=list(stored['payload'].get('question_checkpoint',{}).get('failures',{}).values());task_counts['failed']+=len(new_failures);counts['failed']+=len(new_failures)
        cards.append({**task,'counts':task_counts,'sources':sorted(t for t in titles if t),'page_count':page_count if page_count is not None else len(ids),
            'filenames':list(dict.fromkeys(filenames.get(a,'原材料缺失') for a in ids)), 'worker_active':task['id'] in working})
    return {'counts':counts,'tasks':cards,'items':output[offset:offset+limit],'total':len(output),'offset':offset,'limit':limit}


def confirm(manager,iid,expected,request_id):
    uuid.UUID(request_id)
    with closing(manager.db.connect()) as conn:previous=conn.execute('SELECT * FROM ai_review_requests WHERE request_id=?',(request_id,)).fetchone()
    item=manager.get_item(iid)
    if previous:
        if previous['item_id']!=iid or previous['expected_revision']!=expected:raise ReviewError('核对请求已用于其他内容','review_conflict',item_ids=[iid])
        if item['review_stage']=='publish' and previous['approved_hash']==item['reviewed_hash']:return item
        raise ReviewError('确认后的内容已变化，请重新核对','review_conflict',item_ids=[iid])
    if item['revision']!=expected:raise ReviewError('候选题已变化，请保留修改并刷新','review_conflict',item_ids=[iid])
    if item['review_stage'] in {'published','skipped','deleted','failed','processing'}:raise ReviewError('该题当前无法确认核对','review_conflict',item_ids=[iid])
    draft_revision=item['draft_revision'];before=manager._item_hash(item['form'],item['details'])
    # Compilation intentionally happens outside resource/database locks.
    result=manager.validate_item(iid)
    if result['state']!='ready' or issues(result):raise ReviewError('还有未解决项目，请核对后再确认',issues=issues(result),item_ids=[iid])
    with manager._lock,ASSET_LOCK,manager.db.transaction() as conn:
        current=manager.get_item(iid)
        current_hash=manager._item_hash(current['form'],current['details'])
        if current['revision']!=result['revision'] or current['draft_revision']!=draft_revision or before!=current_hash:
            raise ReviewError('核对检查期间内容或资源已变化，修改已保留','review_conflict',item_ids=[iid])
        stamp=now();conn.execute('UPDATE ai_items SET reviewed_at=?,reviewed_hash=?,revision=revision+1,updated_at=? WHERE id=?',(stamp,current_hash,stamp,iid))
        conn.execute('INSERT INTO ai_review_requests VALUES(?,?,?,?,?)',(request_id,iid,expected,current_hash,stamp))
    return manager.get_item(iid)


def return_review(manager,iid,expected):
    with manager._lock,manager.db.transaction() as conn:
        item=manager.get_item(iid)
        if item['revision']!=expected or item['state'] in {'published','skipped'}:raise ReviewError('候选题已变化，无法退回','review_conflict',item_ids=[iid])
        conn.execute('UPDATE ai_items SET reviewed_at=NULL,reviewed_hash=NULL,revision=revision+1,updated_at=? WHERE id=?',(now(),iid))
    return manager.get_item(iid)


def publish(manager,request_id,selection,task_id=None):
    uuid.UUID(request_id)
    if not selection or len(selection)>50 or len({i['id'] for i in selection})!=len(selection):raise ValueError('请选择 1 至 50 道不同题目')
    signature=encode(selection)
    with manager._lock,ASSET_LOCK,manager.db.transaction() as conn:
        table='ai_publications' if task_id else 'ai_publish_batches'
        previous=conn.execute('SELECT * FROM '+table+' WHERE request_id=?',(request_id,)).fetchone()
        if previous:
            if previous['selection_json']!=signature or task_id and previous['task_id']!=task_id:raise ReviewError('发布请求已用于不同内容','publish_conflict')
            return json.loads(previous['result_json'])
        prepared=[]
        for selected in selection:
            item=manager.get_item(selected['id'])
            if task_id and item['task_id']!=task_id:raise ReviewError('题目不属于本任务','publish_conflict',item_ids=[item['id']])
            if item['revision']!=selected['revision'] or item['review_stage']!='publish':raise ReviewError('题目已变化或尚未人工核对，请退回核对','review_required',issues=issues(item),item_ids=[item['id']])
            if not item['details']['allow_duplicate'] and manager._duplicates(item):raise ReviewError('发现新的重复内容，请重新核对','duplicate_conflict',item_ids=[item['id']])
            bank=manager.store.session(manager.store.task(item['task_id'])['session_id'])['bank_id']
            if item['form'].get('bank_id','system')!=bank:raise ReviewError('候选题不属于任务的题库','publish_conflict')
            prepared.append(item)
        # Duplicate peers across different tasks must also be acknowledged.
        from .agent import fingerprint
        for n,item in enumerate(prepared):
            for peer in prepared[:n]:
                if peer['form'].get('bank_id','system')==item['form'].get('bank_id','system') and fingerprint(peer['form'])==fingerprint(item['form']) and not (peer['details']['allow_duplicate'] and item['details']['allow_duplicate']):
                    raise ReviewError('所选不同任务包含重复题，请先核对','duplicate_conflict',item_ids=[peer['id'],item['id']])
        published=[];collections=set();task_counts={}
        for item in prepared:
            form={**copy.deepcopy(item['form']),'position':len(manager.db._ids_for_point(conn,item['form']['collection_code'],item['form']['point_code'],bank_id=item['form'].get('bank_id','system')))+1,'verified':False}
            revision,question=manager.db.create_question(form,conn)
            closed={'catalog_revision':revision,'question':question,'as_new':False,'affected_collections':[question['collection_code']]}
            conn.execute('INSERT INTO closed_drafts VALUES(?,?,?)',(item['draft_id'],item['draft_revision'],encode(closed)))
            conn.execute('DELETE FROM drafts WHERE id=?',(item['draft_id'],))
            conn.execute("UPDATE ai_items SET state='published',question_id=?,revision=revision+1,updated_at=? WHERE id=?",(question['id'],now(),item['id']))
            published.append({'item_id':item['id'],'task_id':item['task_id'],'question_id':question['id']});collections.add(question['collection_code']);task_counts[item['task_id']]=task_counts.get(item['task_id'],0)+1
        result={'items':published,'affected_collections':sorted(collections),'catalog_revision':revision}
        if task_id:conn.execute('INSERT INTO ai_publications VALUES(?,?,?,?,?)',(request_id,task_id,signature,encode(result),now()))
        else:conn.execute('INSERT INTO ai_publish_batches VALUES(?,?,?,?)',(request_id,signature,encode(result),now()))
        for tid,count in task_counts.items():conn.execute('UPDATE ai_tasks SET message=?,revision=revision+1,updated_at=? WHERE id=?',(f'已加入题库 {count} 道题，其余草稿保留',now(),tid))
    return result
