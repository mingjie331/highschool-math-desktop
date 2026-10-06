from __future__ import annotations

import json
import os
import re
import uuid
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .catalog import APP_DIR, ASSET_DIR, DATA_DIR, CatalogDB, IMAGE_RE, COLLECTION_MAP, DEFAULT_COLLECTION, legacy_collection, PositionConflict
from .latex_service import EXPORT_DIR, ExportManager, LatexError, cached_question_pdf, compile_tex, single_document, validate_question, active_export_dir, cancel_compilations
from .runtime import FRONTEND, latex_status, set_latex_path
from .papers import PaperManager, active_paper_dir
from .assets import ASSET_LOCK, validate_upload, image_references
from .latex_service import start_compilations, submit_preview, compiler
from .compile_queue import CompileCancelled
from .agent import AgentManager
from .agent_routes import agent_router
from .agent_tex import validate_agent_tex


class QuestionWrite(BaseModel):
    collection_code: str | None = None
    point_code: str
    position: int = Field(ge=1)
    type: Literal["single", "multi", "fill", "long"]
    question_tex: str
    options: list[str] = Field(default_factory=list)
    answer_tex: str = ""
    solution_tex: str
    sources: dict[str, Any] | list[Any] = Field(default_factory=dict)
    verified: bool = False
    position_mode: Literal['keep', 'move'] | None = None
    target_order_revision: int | None = Field(default=None, ge=1)


class QuestionUpdate(QuestionWrite):
    revision: int = Field(ge=1)


class PreviewRequest(BaseModel):
    preview_session_id: uuid.UUID | None = None
    preview_revision: int = Field(default=0, ge=0)
    collection_code: str = DEFAULT_COLLECTION
    view: Literal["question", "solution"] = "question"
    type: Literal["single", "multi", "fill", "long"]
    question_tex: str
    options: list[str] = Field(default_factory=list)
    answer_tex: str = ""
    solution_tex: str
    position: int = 1
    sources: dict[str, Any] | list[Any] = Field(default_factory=dict)


db = CatalogDB()
exports = ExportManager(db)
papers = PaperManager(db)
agent = AgentManager(db)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.initialize()
    start_compilations()
    exports.start()
    agent.start()
    yield
    exports.stop()
    papers.stop()
    agent.stop()
    cancel_compilations()


app = FastAPI(title="高中数学题库管理器", version=__import__('backend.runtime',fromlist=['APP_VERSION']).APP_VERSION, lifespan=lifespan)


@app.middleware('http')
async def desktop_access(request: Request, call_next):
    token = os.environ.get('QD_TOKEN')
    if token and request.headers.get('x-desktop-token') != token:
        return JSONResponse({'detail': '此服务仅供题库桌面应用使用。'}, status_code=403)
    return await call_next(request)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PositionConflict):
        return HTTPException(409, {'code': 'position_conflict', 'message': str(exc), 'current_order_revision': exc.current_revision})
    if isinstance(exc, CompileCancelled):
        return HTTPException(409, {'code': 'preview_cancelled', 'message': str(exc)})
    if isinstance(exc, KeyError):
        return HTTPException(404, str(exc).strip("'"))
    if isinstance(exc, RuntimeError):
        return HTTPException(409, str(exc))
    if isinstance(exc, (ValueError, LatexError)):
        return HTTPException(422, str(exc))
    return HTTPException(500, str(exc))


def normalize_sources(value: Any) -> dict[str, Any]:
    """Validate the public source shape while keeping internal source metadata intact."""
    if value is None:
        return {"origins": []}
    if not isinstance(value, dict):
        raise ValueError("来源信息格式错误，请使用题源和原题号输入")
    result = dict(value)
    origins = value.get("origins", [])
    if origins is None:
        origins = []
    if not isinstance(origins, list):
        raise ValueError("来源列表格式错误")
    normalized: list[dict[str, Any]] = []
    for index, origin in enumerate(origins, 1):
        if not isinstance(origin, dict):
            raise ValueError(f"第{index}条来源格式错误")
        item = dict(origin)
        title = str(item.get("title", item.get("paper_id", "")) or "").strip()
        original_number = item.get("original_number")
        number = "" if original_number is None else str(original_number).strip()
        if not title and not number:
            continue
        if not title:
            raise ValueError(f"第{index}条来源：请填写题源")
        item["title"] = title
        if number:
            item["original_number"] = number
        else:
            item.pop("original_number", None)
        normalized.append(item)
    result["origins"] = normalized
    if result.get('source_missing') is True and normalized:
        raise ValueError('题源暂缺时不能同时填写题源')
    return result


def _validated_dict(model: QuestionWrite | QuestionUpdate, previous: dict | None = None) -> dict[str, Any]:
    data = model.model_dump(exclude={"revision"})
    if data.get('collection_code') is None:
        data['collection_code'] = (previous['collection_code'] if previous and db.point_exists(data['point_code'], previous['collection_code']) else legacy_collection(data['point_code']))
    data["sources"] = normalize_sources(data.get("sources"))
    if data['sources'].get('ai_import'):validate_agent_tex(data,image_references(data))
    if data.get('collection_code') not in COLLECTION_MAP:
        raise ValueError('题库集合不存在')
    if not db.point_exists(data["point_code"], data.get('collection_code', DEFAULT_COLLECTION)):
        raise ValueError("考点不存在")
    validate_question(data)
    # Saving requires a real single-question compile. It prevents broken LaTeX entering SQLite.
    compile_tex(single_document(data, solutions=False), "validate", timeout=90)
    compile_tex(single_document(data, solutions=True), "validate", timeout=90)
    return data


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "questions": db.catalog()["total"]}


class LatexSettings(BaseModel):
    path: str = ''


@app.get('/api/desktop/latex')
def get_latex_settings():
    return latex_status()


@app.put('/api/desktop/latex')
def update_latex_settings(payload: LatexSettings):
    try:
        set_latex_path(payload.path)
        return latex_status()
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post('/api/desktop/latex/test')
def test_latex_environment():
    try:
        compile_tex(single_document({'type': 'fill', 'question_tex': r'中文与公式测试：$\sin^2 x+\cos^2 x=1$。', 'position': 1}), 'environment')
        return {'ok': True, 'message': '编译测试通过：XeLaTeX、中文字体及排版宏包可用。'}
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post('/api/desktop/shutdown')
def shutdown_desktop():
    if hasattr(app.state, 'shutdown'):
        app.state.shutdown()
    return {'ok': True}


@app.get("/api/catalog")
def get_catalog() -> dict[str, Any]:
    return db.catalog()


class DraftForm(BaseModel):
    collection_code: str | None = None
    point_code: str = '1.1'
    position: str | int | float | None = 1
    type: Literal['single', 'multi', 'fill', 'long'] = 'single'
    question_tex: str = ''
    options: list[str] = Field(default_factory=list)
    answer_tex: str = ''
    solution_tex: str = ''
    sources: dict[str, Any] = Field(default_factory=dict)
    verified: bool = False


class SourceRow(BaseModel):
    title: str = ''
    originalNumber: str = ''
    metadata: dict[str, Any] = Field(default_factory=dict)


class DraftContent(BaseModel):
    form: DraftForm
    source_rows: list[SourceRow] = Field(default_factory=list)


class DraftWrite(BaseModel):
    revision: int = Field(ge=0)
    source_question_id: str | None = None
    base_revision: int | None = Field(default=None, ge=1)
    content: DraftContent
    position_mode: Literal['keep', 'move'] | None = None
    target_order_revision: int | None = Field(default=None, ge=1)


class DraftPublish(BaseModel):
    revision: int = Field(ge=1)
    as_new: bool = False


@app.get('/api/search')
def search_questions(q: str = '', collection_code: str | None = None):
    try:
        items = db.search(q, collection_code)
        return {'items': items, 'total': len(items)}
    except Exception as exc:
        raise _http_error(exc) from exc


@app.get('/api/drafts')
def list_drafts():
    return db.list_drafts()


@app.get('/api/drafts/{draft_id}')
def get_draft(draft_id: str):
    try:
        return db.get_draft(draft_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.put('/api/drafts/{draft_id}')
def save_draft(draft_id: uuid.UUID, payload: DraftWrite):
    try:
        content = payload.content.model_dump()
        return db.save_draft(str(draft_id), payload.revision, payload.source_question_id,
                             payload.base_revision, content, payload.position_mode, payload.target_order_revision)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.delete('/api/drafts/{draft_id}')
def discard_draft(draft_id: str, revision: int = Query(..., ge=1)):
    try:
        db.discard_draft(draft_id, revision)
        return {'deleted_id': draft_id}
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post('/api/drafts/{draft_id}/publish')
def publish_draft(draft_id: str, payload: DraftPublish):
    try:
        previous = db.published_draft(draft_id, payload.revision, payload.as_new)
        if previous:
            return previous
        draft = db.get_draft(draft_id)
        if not draft['source_question_id'] and draft['content']['form'].get('sources',{}).get('ai_import'):
            raise RuntimeError('AI 候选草稿请在“AI 录题”中重新校验并确认入库；编辑内容已保留。')
        if draft['revision'] != payload.revision:
            raise RuntimeError('草稿已变化，请重新校验并保存')
        data = dict(draft['content']['form'])
        data['sources'] = {**data.get('sources', {}), 'origins': [
            {**row.get('metadata', {}), 'title': row.get('title', ''), 'original_number': row.get('originalNumber', '')}
            for row in draft['content']['source_rows']]}
        data = _validated_dict(QuestionWrite.model_validate(data))
        result, changed = db.publish_draft(draft_id, payload.revision, data, payload.as_new)
        if changed:
            exports.invalidate(*result['affected_collections'])
        return result
    except Exception as exc:
        raise _http_error(exc) from exc


@app.get("/api/questions/{question_id}")
def get_question(question_id: str) -> dict[str, Any]:
    question = db.get_question(question_id)
    if not question:
        raise HTTPException(404, "题目不存在")
    return question


@app.post("/api/questions", status_code=201)
def create_question(payload: QuestionWrite) -> dict[str, Any]:
    try:
        data = _validated_dict(payload)
        catalog_revision, question = db.create_question(data)
        exports.invalidate(question['collection_code'])
        return {"catalog_revision": catalog_revision, "question": question}
    except Exception as exc:
        raise _http_error(exc) from exc


@app.patch("/api/questions/{question_id}")
def update_question(question_id: str, payload: QuestionUpdate) -> dict[str, Any]:
    try:
        previous = db.get_question(question_id)
        data = _validated_dict(payload, previous)
        catalog_revision, question = db.update_question(question_id, payload.revision, data)
        exports.invalidate(question['collection_code'])
        if previous and previous.get('collection_code') != data.get('collection_code'):
            exports.invalidate(previous['collection_code'])
        return {"catalog_revision": catalog_revision, "question": question}
    except Exception as exc:
        raise _http_error(exc) from exc


@app.delete("/api/questions/{question_id}")
def delete_question(question_id: str, revision: int = Query(..., ge=1)) -> dict[str, Any]:
    try:
        catalog_revision, removed = db.delete_question(question_id, revision)
        db.cleanup_assets(removed)
        exports.invalidate(removed['collection_code'])
        return {"catalog_revision": catalog_revision, "deleted_id": question_id}
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/api/preview")
async def preview(payload: PreviewRequest, request: Request) -> Response:
    data = payload.model_dump(exclude={"view", 'preview_session_id', 'preview_revision'})
    data.setdefault("id", "preview")
    data.setdefault("point_code", "1.1")
    data.setdefault("verified", False)
    try:
        data["sources"] = normalize_sources(data.get("sources"))
        if data['sources'].get('ai_import'):validate_agent_tex(data,image_references(data))
        validate_question(data)
        job = submit_preview(single_document(data, solutions=payload.view == "solution"),
                             str(payload.preview_session_id) if payload.preview_session_id else None,
                             payload.preview_revision)
        future = asyncio.wrap_future(job.future)
        async def disconnected():
            # Body validation has consumed the request. Wait for the actual ASGI
            # event instead of is_disconnected's immediately-cancelled poll,
            # which cannot traverse BaseHTTPMiddleware's receive task group.
            while True:
                if (await request.receive())['type'] == 'http.disconnect':
                    return
        disconnect = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait([future, disconnect], return_when=asyncio.FIRST_COMPLETED)
            if disconnect in done and not future.done():
                compiler.cancel_job(job)
            pdf = await future
        except asyncio.CancelledError:
            compiler.cancel_job(job)
            raise
        finally:
            disconnect.cancel()
            try:
                await disconnect
            except asyncio.CancelledError:
                pass
        return Response(content=pdf, media_type="application/pdf")
    except Exception as exc:
        raise _http_error(exc) from exc


@app.get("/api/questions/{question_id}/pdf")
def question_pdf(question_id: str, view: Literal["question", "solution"] = "question") -> FileResponse:
    try:
        return FileResponse(cached_question_pdf(db, question_id, view), media_type="application/pdf")
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post("/api/assets", status_code=201)
async def upload_asset(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".pdf"}:
        raise HTTPException(422, "只允许上传 PNG、JPG、JPEG 或 PDF")
    content = await file.read(12 * 1024 * 1024 + 1)
    if len(content) > 12 * 1024 * 1024:
        raise HTTPException(413, "图片不能超过 12MB")
    try:
        await asyncio.to_thread(validate_upload, content, suffix)
    except ValueError as exc:
        raise _http_error(exc) from exc
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    name = str(uuid.uuid4()) + suffix
    target = ASSET_DIR / name
    temporary = target.with_suffix(target.suffix + '.tmp')
    with ASSET_LOCK:
        try:
            temporary.write_bytes(content)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    latex_path = f"assets/{name}"
    return {"latex_path": latex_path, "url": f"/assets/{name}", "original_name": file.filename}


class ExportRequest(BaseModel):
    collection_code: str = DEFAULT_COLLECTION


@app.post('/api/exports')
def start_export(payload: ExportRequest = ExportRequest()):
    try:
        return exports.schedule(payload.collection_code)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.get('/api/exports/status')
def export_status(collection_code: str = DEFAULT_COLLECTION):
    try:
        return exports.status(collection_code)
    except Exception as exc:
        raise _http_error(exc) from exc


class PoolRemove(BaseModel):
    question_ids: list[str] = Field(min_length=1)


class PaperRequest(BaseModel):
    mode: Literal['manual', 'random']
    question_ids: list[str] | None = None
    count: int | None = None


@app.get('/api/pool')
def get_pool():
    return db.pool_state()


@app.put('/api/pool/{question_id}')
def add_to_pool(question_id: str):
    try:
        db.pool_add(question_id)
        return db.pool_state()
    except Exception as exc:
        raise _http_error(exc) from exc


@app.delete('/api/pool/{question_id}')
def remove_from_pool(question_id: str):
    try:
        db.pool_remove([question_id])
        return db.pool_state()
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post('/api/pool/remove')
def remove_from_pool_batch(payload: PoolRemove):
    try:
        db.pool_remove(payload.question_ids)
        return db.pool_state()
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post('/api/pool/undo')
def undo_pool_remove():
    try:
        db.pool_undo()
        return db.pool_state()
    except Exception as exc:
        raise _http_error(exc) from exc


@app.post('/api/papers')
def create_paper(payload: PaperRequest):
    try:
        return papers.schedule(payload.mode, payload.question_ids, payload.count)
    except Exception as exc:
        raise _http_error(exc) from exc


@app.get('/api/papers/status')
def paper_status():
    return papers.status()


@app.get('/api/papers/latest')
def latest_paper():
    folder = active_paper_dir()
    if not folder:
        raise HTTPException(404, '尚无成功生成的训练卷')
    return json.loads((folder / 'paper_manifest.json').read_text('utf-8'))


@app.get('/api/papers/files/{kind}')
def paper_file(kind: Literal['question', 'solution', 'manifest']):
    folder = active_paper_dir()
    if not folder:
        raise HTTPException(404, '尚无成功生成的训练卷')
    manifest = json.loads((folder / 'paper_manifest.json').read_text('utf-8'))
    filename = 'paper_manifest.json' if kind == 'manifest' else manifest['files'][kind]
    return FileResponse(folder / filename)


ASSET_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=ASSET_DIR), name="assets")
@app.get('/exports/{filename}')
def export_file(filename: str, collection_code: str = DEFAULT_COLLECTION):
    try:
        allowed = set(exports.file_names(collection_code).values()) | {'export_manifest.json', 'questions.tex', 'solutions.tex'}
        folder = active_export_dir(collection_code)
    except ValueError as exc:
        raise _http_error(exc) from exc
    if filename not in allowed or not folder or not (folder / filename).is_file():
        raise HTTPException(404, '尚无当前集合的成功导出文件')
    return FileResponse(folder / filename)


app.include_router(agent_router(agent,_http_error,exports))
frontend_dist = FRONTEND
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    @app.get("/")
    def missing_frontend() -> JSONResponse:
        return JSONResponse({"message": "前端尚未构建，请运行 npm run build"})
