"""Task failures and deletion tombstones never constitute review candidates."""
import json
import uuid
from contextlib import closing
from .agent_store import encode,now
from .tex_layout import has_stem
from .agent_review import ReviewError


def legacy_failure(item):
    return (item.get('state') not in {'published','skipped','deleted'} and item.get('draft_revision')==1
            and not has_stem(item.get('form',{}).get('question_tex',''))
)


def failures(manager,task,items):
    result=list(task['payload'].get('question_checkpoint',{}).get('failures',{}).values())
    for item in items:
        if legacy_failure(item):
            result.append({'id':'legacy:'+item['id'],'item_id':item['id'],'original_number':item['details'].get('original_number',''),
                           'regions':item['details'].get('regions',[]),'stage':'recognition',
                           'code':'legacy_empty_stem','message':(item['details'].get('stage_error') or {}).get('message','题干提取未完成')})
    for failure in result:
        failure['sources']=[{'filename':page['filename'],'page_number':page.get('page_number',1),'rect':r['rect']}
                            for r in failure.get('regions',[]) for page in [manager.store.attachment(r['image_id'])]]
    return result


def delete_candidate(manager,iid,expected,draft_expected,request_id):
    uuid.UUID(request_id)
    with manager._lock,manager.db.transaction() as conn:
        row=conn.execute('SELECT * FROM ai_items WHERE id=?',(iid,)).fetchone()
        if not row:raise KeyError('候选题不存在')
        details=json.loads(row['details_json'])
        if row['state']=='deleted':
            if details.get('deletion')=={'request_id':request_id,'revision':expected,'draft_revision':draft_expected}:return {'id':iid,'deleted':True}
            raise ReviewError('该候选题已删除','candidate_deleted',item_ids=[iid])
        draft=conn.execute('SELECT * FROM drafts WHERE id=?',(row['draft_id'],)).fetchone()
        if row['state']=='published' or row['question_id'] or not draft:raise ReviewError('已入库或已关闭的题目不能通过候选删除','candidate_closed',item_ids=[iid])
        if row['revision']!=expected or draft['revision']!=draft_expected:raise ReviewError('候选或草稿已变化，请核对最新内容后再删除','review_conflict',item_ids=[iid])
        task=conn.execute('SELECT payload_json FROM ai_tasks WHERE id=?',(row['task_id'],)).fetchone();payload=json.loads(task[0])
        checkpoint=payload.get('question_checkpoint',{})
        deleted=set(checkpoint.get('deleted_keys',[]))
        for key,value in list(checkpoint.get('completed',{}).items()):
            if value==iid:deleted.add(key);del checkpoint['completed'][key]
        checkpoint['deleted_keys']=sorted(deleted)
        checkpoint['item_ids']=[i for i in checkpoint.get('item_ids',[]) if i!=iid]
        for key in list(checkpoint.get('failures',{})):
            if checkpoint['failures'][key].get('item_id')==iid:del checkpoint['failures'][key]
        payload['question_checkpoint']=checkpoint
        recognition=payload.get('recognition_checkpoint',{})
        ids=recognition.get('item_ids',[])
        if iid in ids:
            index=ids.index(iid);candidate=recognition.get('candidates',[])
            if index<len(candidate):candidate[index]={'deleted':True}
            ids[index]=None
        conn.execute('INSERT INTO closed_drafts VALUES(?,?,NULL)',(row['draft_id'],draft_expected))
        conn.execute('DELETE FROM drafts WHERE id=?',(row['draft_id'],))
        conn.execute("UPDATE ai_items SET state='deleted',details_json=?,validated_hash=NULL,reviewed_at=NULL,reviewed_hash=NULL,revision=revision+1,updated_at=? WHERE id=?",
                     (encode({'deletion':{'request_id':request_id,'revision':expected,'draft_revision':draft_expected}}),now(),iid))
        conn.execute('UPDATE ai_tasks SET payload_json=?,revision=revision+1,updated_at=? WHERE id=?',(encode(payload),now(),row['task_id']))
        if iid in manager._compile_jobs:
            from .latex_service import compiler
            compiler.cancel_job(manager._compile_jobs[iid])
    return {'id':iid,'deleted':True}
