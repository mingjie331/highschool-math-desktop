import asyncio
import uuid
from typing import Literal
from fastapi import APIRouter,HTTPException,UploadFile,File,Request,Query
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from .agent import AgentManager
from .agent_models import Region

class NewSession(BaseModel):
    bank_id:str="system"
    title:str=Field(default='图片录题',max_length=80)
class Credentials(BaseModel):
    api_key:str=Field(max_length=512)
    prices:dict[str,float]|None=None
class DocumentPair(BaseModel):
    question_document_id:uuid.UUID
    answer_document_id:uuid.UUID
class ImportRequest(BaseModel):
    session_id:uuid.UUID
    attachment_ids:list[uuid.UUID]=Field(min_length=1,max_length=20)
    instruction:str=Field(default='提取题目，补充缺失答案解析并按知识点分类',max_length=8000)
    source_title:str=Field(default='',max_length=1000)
    request_id:uuid.UUID
    input_regions:list[Region]|None=Field(default=None,max_length=200)
    question_numbers:str=Field(default='',max_length=300)
    target_document_id:uuid.UUID|None=None
    document_pairs:list[DocumentPair]|None=Field(default=None,max_length=10)
class ItemChange(BaseModel):
    revision:int=Field(ge=1)
    changes:dict
class DeleteCandidate(BaseModel):
    revision:int=Field(ge=1)
    draft_revision:int=Field(ge=1)
    request_id:uuid.UUID
class RetryRequest(BaseModel):
    item_ids:list[uuid.UUID]|None=None
    failure_ids:list[str]|None=None
class Selection(BaseModel):id:uuid.UUID;revision:int=Field(ge=1)
class ReviewRequest(BaseModel):
    revision:int=Field(ge=1)
    request_id:uuid.UUID
class RevisionRequest(BaseModel):revision:int=Field(ge=1)
class PublishRequest(BaseModel):
    request_id:uuid.UUID
    items:list[Selection]=Field(min_length=1,max_length=50)
class ChatRequest(BaseModel):
    text:str=Field(min_length=1,max_length=8000)
    request_id:uuid.UUID
class CropRequest(BaseModel):
    revision:int=Field(ge=1)
    region:Region
    field:Literal['question_tex','answer_tex','solution_tex']='question_tex'
    figure_id:str|None=Field(default=None,max_length=80)
class RestructureRequest(BaseModel):
    items:list[Selection]=Field(min_length=1,max_length=50)
    groups:list[list[Region]]=Field(min_length=1,max_length=20)


def agent_router(manager:AgentManager,error_mapper,exports):
    router=APIRouter(prefix='/api/agent',tags=['AI录题'])
    def run(fn,*args,**kwargs):
        try:return fn(*args,**kwargs)
        except Exception as exc:
            from .agent_review import ReviewError
            if isinstance(exc,ReviewError):raise HTTPException(409,exc.detail) from exc
            raise error_mapper(exc) from exc

    @router.get('/workbench')
    def workbench(task_id:uuid.UUID|None=None,source:str|None=None,review_stage:Literal['review','publish','processing','published','skipped']|None=None,
                  offset:int=Query(default=0,ge=0),limit:int=Query(default=100,ge=1,le=200),bank_id:str="system"):
        return run(manager.workbench,task_id=str(task_id) if task_id else None,source=source,review_stage=review_stage,offset=offset,limit=limit,bank_id=bank_id)
    @router.post('/publish')
    def publish_batch(payload:PublishRequest):
        result=run(manager.publish_batch,str(payload.request_id),[{'id':str(i.id),'revision':i.revision} for i in payload.items]);exports.invalidate(*result['affected_collections']);return result
    @router.post('/items/{iid}/confirm-review')
    async def confirm_review(iid:uuid.UUID,payload:ReviewRequest):
        return await asyncio.to_thread(run,manager.confirm_review,str(iid),payload.revision,str(payload.request_id))
    @router.post('/items/{iid}/return-review')
    def return_review(iid:uuid.UUID,payload:RevisionRequest):return run(manager.return_review,str(iid),payload.revision)

    @router.get('/config')
    def status():return manager.config_status()
    @router.put('/credentials')
    def configure(payload:Credentials):
        import os
        if not os.environ.get('QD_TOKEN'):raise HTTPException(403,'请从桌面应用设置配置密钥')
        run(manager.configure,payload.api_key,payload.prices)
        return manager.config_status()
    @router.post('/config/test')
    async def test():
        try:return await manager.provider.test()
        except Exception as exc:raise error_mapper(exc) from exc
    @router.get('/sessions')
    def sessions(bank_id:str="system"):return run(manager.sessions,bank_id)
    @router.post('/sessions',status_code=201)
    def create(payload:NewSession):return run(manager.create_session,payload.title,payload.bank_id)
    @router.get('/sessions/{sid}')
    def session(sid:uuid.UUID,compact:bool=False):return run(manager.store.session,str(sid),compact)
    @router.post('/sessions/{sid}/attachments',status_code=201)
    async def attach(sid:uuid.UUID,file:UploadFile=File(...)):
        limit=(32 if (file.filename or '').lower().endswith('.pdf') else 12)*1024*1024
        content=await file.read(limit+1)
        if len(content)>limit:raise HTTPException(413,'PDF 单文件不能超过 32 MiB，图片不能超过 12 MiB')
        return await asyncio.to_thread(run,manager.attach,str(sid),file.filename or '截图.png',content)
    @router.get('/documents/{did}')
    def document(did:uuid.UUID):return run(manager.store.document,str(did))
    @router.get('/documents/{did}/pages')
    def pages(did:uuid.UUID):return run(manager.store.document,str(did))['pages']
    @router.get('/documents/{did}/file')
    def original(did:uuid.UUID):
        from .agent_documents import original_document_file
        return FileResponse(run(original_document_file,manager,str(did)),media_type='application/pdf')
    @router.get('/attachments/{aid}/image')
    def image(aid:uuid.UUID):return FileResponse(run(manager.attachment_file,str(aid)))
    @router.get('/catalog')
    def catalog():return run(manager.taxonomy)
    @router.post('/imports',status_code=202)
    def start(payload:ImportRequest):
        return run(manager.start_import,str(payload.session_id),[str(i) for i in payload.attachment_ids],payload.instruction,payload.source_title,str(payload.request_id),[region.model_dump() for region in payload.input_regions] if payload.input_regions is not None else None,
            payload.question_numbers,str(payload.target_document_id) if payload.target_document_id else None,[pair.model_dump(mode='json') for pair in payload.document_pairs] if payload.document_pairs is not None else None)
    @router.get('/imports/{tid}')
    def task(tid:uuid.UUID,compact:bool=False):
        result=run(manager.get_task,str(tid))
        if compact:
            result['payload']={key:result['payload'][key] for key in ['attachment_ids','instruction','source_title','page_count'] if key in result['payload']}
            result['items']=[{key:item[key] for key in ['id','question_id','state','revision','review_stage']} for item in result['items']]
        return result
    @router.post('/imports/{tid}/cancel')
    def cancel(tid:uuid.UUID):return run(manager.cancel,str(tid))
    @router.post('/imports/{tid}/retry')
    def retry(tid:uuid.UUID,payload:RetryRequest):return run(manager.retry,str(tid),[str(i) for i in payload.item_ids] if payload.item_ids is not None else None,payload.failure_ids)
    @router.post('/imports/{tid}/reprocess')
    def reprocess(tid:uuid.UUID,payload:RetryRequest):return run(manager.reprocess,str(tid),[str(i) for i in payload.item_ids or []])
    @router.post('/imports/{tid}/solve')
    def solve(tid:uuid.UUID,payload:RetryRequest):return run(manager.solve,str(tid),[str(i) for i in payload.item_ids or []])
    @router.post('/imports/{tid}/messages')
    def chat(tid:uuid.UUID,payload:ChatRequest):return run(manager.chat,str(tid),payload.text,str(payload.request_id))
    @router.post('/imports/{tid}/restructure')
    def restructure(tid:uuid.UUID,payload:RestructureRequest):
        return run(manager.restructure,str(tid),[{'id':str(i.id),'revision':i.revision} for i in payload.items],[[region.model_dump() for region in group] for group in payload.groups])
    @router.post('/imports/{tid}/publish')
    def publish(tid:uuid.UUID,payload:PublishRequest):
        result=run(manager.publish,str(tid),str(payload.request_id),[{'id':str(i.id),'revision':i.revision} for i in payload.items])
        exports.invalidate(*result['affected_collections'])
        return result
    @router.delete('/items/{iid}')
    def delete_candidate(iid:uuid.UUID,payload:DeleteCandidate):return run(manager.delete_candidate,str(iid),payload.revision,payload.draft_revision,str(payload.request_id))
    @router.patch('/items/{iid}')
    def update(iid:uuid.UUID,payload:ItemChange):return run(manager.update_item,str(iid),payload.revision,payload.changes)
    @router.get('/items/{iid}')
    def item(iid:uuid.UUID):return run(manager.get_item,str(iid))
    @router.get('/items/{iid}/materials')
    def materials(iid:uuid.UUID):
        item=run(manager.get_item,str(iid));task=run(manager.store.task,item['task_id'])
        return [manager.store.attachment_row(run(manager.store.attachment,aid)) for aid in task['payload']['attachment_ids']]
    @router.post('/items/{iid}/validate')
    async def validate(iid:uuid.UUID):return await asyncio.to_thread(run,manager.validate_item,str(iid))
    @router.post('/items/{iid}/skip')
    def skip(iid:uuid.UUID,payload:Selection):
        if str(iid)!=str(payload.id):raise HTTPException(422,'题目 ID 不匹配')
        return run(manager.skip,str(iid),payload.revision)
    @router.post('/items/{iid}/figure')
    def figure(iid:uuid.UUID,payload:CropRequest):return run(manager.crop_figure,str(iid),payload.revision,payload.region.model_dump(),payload.field,payload.figure_id)
    return router
