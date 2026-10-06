"""Local, bounded PDF ingestion. PDFs never execute actions or leave the machine."""
import hashlib
import io
import math
import threading
import uuid
from contextlib import closing
from pathlib import Path
from .assets import validate_upload
from .agent_store import now

PDFIUM_LOCK=threading.RLock()
MAX_PAGES=20
MAX_PIXELS=20_000_000


def ingest_pdf(manager,sid,filename,content):
    if len(content)>32*1024*1024:raise ValueError('PDF 单文件不能超过 32 MiB')
    validate_upload(content,'.pdf')
    from pypdf import PdfReader
    count=len(PdfReader(io.BytesIO(content),strict=True).pages)
    if not 1<=count<=MAX_PAGES:raise ValueError('AI 录题 PDF 须包含 1 至 20 页')
    did=str(uuid.uuid4());relative='documents/'+did+'.pdf'
    original=manager.store.directory/relative
    created=[];rows=[]
    try:
        original.parent.mkdir(parents=True,exist_ok=True);created.append(original);original.write_bytes(content)
        import pypdfium2 as pdfium
        with PDFIUM_LOCK, pdfium.PdfDocument(content) as pdf:
            for number in range(count):
                with closing(pdf[number]) as page:
                    w,h=page.get_size()
                    if not math.isfinite(w*h) or w<=0 or h<=0:raise ValueError('PDF 页面尺寸无效')
                    scale=min(200/72,math.sqrt(MAX_PIXELS/(w*h)))
                    with closing(page.render(scale=scale)) as bitmap:
                        image=bitmap.to_pil().convert('RGB');width,height=image.size
                        if width*height>MAX_PIXELS:
                            image.thumbnail((int(width*.999),int(height*.999)));width,height=image.size
                        aid=str(uuid.uuid4());ref='attachments/'+aid+'.png';target=manager.store.directory/ref
                        target.parent.mkdir(parents=True,exist_ok=True);created.append(target);image.save(target,'PNG')
                        rows.append((aid,sid,Path(filename).name[:160],ref,hashlib.sha256(target.read_bytes()).hexdigest(),width,height,now(),did,number+1))
        with manager.db.transaction() as conn:
            conn.execute('INSERT INTO ai_documents VALUES(?,?,?,?,?,?,?)',(did,sid,Path(filename).name[:160],relative,hashlib.sha256(content).hexdigest(),count,now()))
            conn.executemany('INSERT INTO ai_attachments(id,session_id,filename,relative_path,sha256,width,height,created_at,document_id,page_number) VALUES(?,?,?,?,?,?,?,?,?,?)',rows)
    except BaseException:
        for path in created:path.unlink(missing_ok=True)
        raise
    return manager.store.document(did)


def original_document_file(manager,did):
    with closing(manager.db.connect()) as conn:
        row=conn.execute('SELECT relative_path FROM ai_documents WHERE id=?',(did,)).fetchone()
    if not row:raise KeyError('PDF 文档不存在')
    target=(manager.store.directory/row[0]).resolve()
    if not target.is_relative_to((manager.store.directory/'documents').resolve()) or not target.is_file():raise KeyError('原 PDF 文件缺失')
    return target
