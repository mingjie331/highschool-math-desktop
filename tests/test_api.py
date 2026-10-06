import io
import asyncio
import json
import sqlite3
import uuid
import threading
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter

from tests.support import IsolatedCase, ROOT, payload, catalog, runtime, latex_service, papers


class ApiTests(IsolatedCase):
    def setUp(self):
        super().setUp()
        from backend import app as module
        self.module = module
        self.stack.enter_context(patch.multiple(module, db=self.db,
            exports=latex_service.ExportManager(self.db), papers=papers.PaperManager(self.db),
            agent=__import__('backend.agent',fromlist=['AgentManager']).AgentManager(self.db),
            ASSET_DIR=self.data/'assets'))
        self.client = self.stack.enter_context(TestClient(module.app, raise_server_exceptions=False))

    def save_draft(self, question, mode='keep', order=None, revision=0, draft_id=None):
        draft_id = draft_id or str(uuid.uuid4())
        response = self.client.put('/api/drafts/'+draft_id, json={
            'revision': revision, 'source_question_id': question['id'], 'base_revision': question['revision'],
            'content': {'form': payload(position=question['position']), 'source_rows': []},
            'position_mode': mode, 'target_order_revision': order,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_position_conflict_is_distinct_and_draft_can_be_confirmed(self):
        question = self.create()
        draft = self.save_draft(question, 'move', question['order_revision'])
        self.create(position=2)
        with patch.object(self.module, 'compile_tex', return_value=b'%PDF'):
            result = self.client.post(f"/api/drafts/{draft['id']}/publish", json={'revision':1})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()['detail']['code'], 'position_conflict')
        self.assertEqual(self.db.get_draft(draft['id'])['revision'], 1)
        current = self.db.point_order_revision('gaoyi-second', '6.1')
        confirmed = self.save_draft(question, 'move', current, 1, draft['id'])
        with patch.object(self.module, 'compile_tex', return_value=b'%PDF'):
            result = self.client.post(f"/api/drafts/{draft['id']}/publish", json={'revision':confirmed['revision']})
        self.assertEqual(result.status_code, 200, result.text)

    def test_keep_mode_uses_latest_position_and_publish_retry_is_idempotent(self):
        question = self.create()
        draft = self.save_draft(question)
        self.create(position=1)
        with patch.object(self.module, 'compile_tex', return_value=b'%PDF'):
            first = self.client.post(f"/api/drafts/{draft['id']}/publish", json={'revision':1})
            second = self.client.post(f"/api/drafts/{draft['id']}/publish", json={'revision':1})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()['question']['position'], 2)

    def test_source_content_conflict_and_save_as_new_survive(self):
        question = self.create()
        draft = self.save_draft(question)
        self.db.update_question(question['id'], question['revision'], payload(answer_tex='新答案'))
        with patch.object(self.module, 'compile_tex', return_value=b'%PDF'):
            conflict = self.client.post(f"/api/drafts/{draft['id']}/publish", json={'revision':1})
            fresh = self.client.post(f"/api/drafts/{draft['id']}/publish", json={'revision':1, 'as_new':True})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(fresh.status_code, 200, fresh.text)
        self.assertNotEqual(fresh.json()['question']['id'], question['id'])
        self.assertEqual(fresh.json()['question']['position'], 2)
        self.assertEqual(self.db.get_question(question['id'])['answer_tex'], '新答案')

    def test_published_ai_question_remains_editable_in_normal_editor(self):
        question=self.create(sources={'origins':[],'ai_import':{'task_id':'test','item_id':'test'}})
        draft_id=str(uuid.uuid4())
        content={'form':{**payload(), 'sources':question['sources'],'question_tex':'人工修订后的题干'},'source_rows':[]}
        self.db.save_draft(draft_id,0,question['id'],question['revision'],content,position_mode='keep')
        with patch.object(self.module,'compile_tex',return_value=b'%PDF'):
            response=self.client.post('/api/drafts/'+draft_id+'/publish',json={'revision':1})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.db.get_question(question['id'])['question_tex'],'人工修订后的题干')

    def test_ai_provenance_preview_rejects_file_commands_before_compilation(self):
        with patch.object(self.module,'submit_preview') as compile_item:
            response=self.client.post('/api/preview',json={**payload(question_tex=r'\input{settings.json}',sources={'origins':[],'ai_import':{'task_id':'test'}}),'view':'question'})
        self.assertEqual(response.status_code,422,response.text)
        compile_item.assert_not_called()

    def test_bad_uploads_leave_no_files(self):
        before = set((self.data/'assets').iterdir())
        for filename, data in [('fake.png', b'not PNG'), ('empty.jpg', b''), ('bad.pdf', b'%PDF-1.7 broken')]:
            result = self.client.post('/api/assets', files={'file':(filename,data)})
            self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(before, set((self.data/'assets').iterdir()))
        result = self.client.post('/api/assets', files={'file':('big.png', b'x'*(12*1024*1024+1))})
        self.assertEqual(result.status_code, 413)

    def test_valid_png_jpeg_and_pdf_uploads(self):
        for format, filename in [('PNG','图.png'), ('JPEG','图.jpg')]:
            buffer = io.BytesIO(); Image.new('RGB',(10,10)).save(buffer,format=format)
            result = self.client.post('/api/assets',files={'file':(filename,buffer.getvalue())})
            self.assertEqual(result.status_code,201,result.text)
            self.assertEqual((self.data/result.json()['latex_path']).read_bytes(), buffer.getvalue())
        buffer = io.BytesIO(); writer=PdfWriter();writer.add_blank_page(100,100);writer.write(buffer)
        result=self.client.post('/api/assets',files={'file':('图.pdf',buffer.getvalue())})
        self.assertEqual(result.status_code,201,result.text)

    def test_corrupt_settings_are_repaired_through_api(self):
        runtime.SETTINGS.write_text('{broken',encoding='utf-8')
        result=self.client.get('/api/desktop/latex')
        self.assertEqual(result.status_code,200)
        self.assertTrue(result.json()['warning'])
        result=self.client.put('/api/desktop/latex',json={'path':''})
        self.assertEqual(result.status_code,200)
        self.assertFalse(result.json()['warning'])

    def test_http_disconnect_cancels_active_preview_through_middleware(self):
        started=threading.Event();stopped=threading.Event()
        def controlled_compile(source,name,timeout,passes,resource_root,cancelled):
            started.set()
            cancelled.wait(3)
            if cancelled.is_set():stopped.set()
            return b'%PDF'
        body=json.dumps({'type':'fill','question_tex':'题干','solution_tex':'解析','options':[],
                         'preview_session_id':str(uuid.uuid4()),'preview_revision':1}).encode()
        async def scenario():
            sent=False
            async def receive():
                nonlocal sent
                if not sent:
                    sent=True
                    return {'type':'http.request','body':body,'more_body':False}
                while not started.is_set():await asyncio.sleep(.01)
                return {'type':'http.disconnect'}
            async def send(message):pass
            scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.3'},'http_version':'1.1',
                   'method':'POST','scheme':'http','path':'/api/preview','raw_path':b'/api/preview','query_string':b'',
                   'headers':[(b'content-type',b'application/json')], 'client':('127.0.0.1',1234),'server':('127.0.0.1',80)}
            await asyncio.wait_for(self.module.app(scope,receive,send),timeout=2)
        with patch.object(latex_service,'_compile_tex_unlocked',side_effect=controlled_compile):
            asyncio.run(scenario())
        self.assertTrue(stopped.wait(1),'disconnect did not stop compiler')


class ExtraRegressionTests(IsolatedCase):
    def test_schema4_upgrade_preserves_user_data_drafts_pool_and_undo(self):
        question=self.create(question_tex='用户自建题',sources={'origins':[{'title':'用户题源','custom':'保留'}]})
        draft_id=str(uuid.uuid4());content=self.draft(question,question_tex='未发布输入')
        self.db.save_draft(draft_id,0,question['id'],question['revision'],content)
        other=self.create(position=2)
        self.db.pool_add(question['id']);self.db.pool_add(other['id']);self.db.pool_remove([other['id']])
        with self.db.transaction() as conn:
            conn.execute('alter table knowledge_points drop column order_revision')
            conn.execute('alter table drafts drop column position_mode')
            conn.execute('alter table drafts drop column target_order_revision')
            conn.execute("update metadata set value='4' where key='schema_version'")
        self.db.initialize()
        actual=self.db.get_question(question['id'])
        for field in ['id','revision','created_at','updated_at','question_tex','sources','position']:
            self.assertEqual(actual[field],question[field])
        self.assertEqual(self.db.get_draft(draft_id)['content'],content)
        self.assertEqual(self.db.get_draft(draft_id)['base_revision'],question['revision'])
        self.assertTrue(self.db.pool_state()['can_undo'])
        self.db.pool_undo()
        self.assertEqual([item['id'] for item in self.db.pool_items()],[question['id'],other['id']])
        self.assertTrue(list((self.data/'backups').glob('*schema-4-*.sqlite3')))

    def test_migration_failure_rolls_back_and_backup_remains_valid(self):
        path=self.data/'rollback.sqlite3'
        with sqlite3.connect((ROOT/'resources/seed/question_bank.sqlite3').as_uri()+'?mode=ro&immutable=1',uri=True) as source:
            with sqlite3.connect(path) as target:source.backup(target)
        source.close();target.close()
        database=catalog.CatalogDB(path)
        with patch.object(database,'_migrate_bridge',side_effect=RuntimeError('injected migration failure')):
            with self.assertRaises(RuntimeError):database.initialize()
        with sqlite3.connect(path) as conn:
            self.assertNotIn('collection_code',[row[1] for row in conn.execute('pragma table_info(questions)')])
            self.assertEqual(conn.execute('select count(*) from questions').fetchone()[0],627)
            self.assertEqual(conn.execute('pragma integrity_check').fetchone()[0],'ok')
        conn.close()
        self.assertGreaterEqual(len(list((self.data/'backups').glob('*.sqlite3'))),2)

    def test_invalid_schema_marker_is_rejected(self):
        for value in ['future','-1','5.0']:
            with self.db.transaction() as conn:conn.execute("update metadata set value=? where key='schema_version'",(value,))
            with self.assertRaises(RuntimeError):self.db.initialize()

    def test_scope_move_bumps_both_points_but_content_does_not(self):
        question=self.create()
        old=self.db.point_order_revision('gaoyi-second','6.1')
        target=self.db.point_order_revision('gaoyi-second','6.2')
        self.db.update_question(question['id'],question['revision'],payload(point_code='6.2'))
        self.assertEqual(self.db.point_order_revision('gaoyi-second','6.1'),old+1)
        self.assertEqual(self.db.point_order_revision('gaoyi-second','6.2'),target+1)

    def test_settings_write_error_is_reported(self):
        with patch.object(runtime.os,'replace',side_effect=PermissionError('read only')):
            with self.assertRaises(PermissionError):runtime.set_latex_path('')
        self.assertFalse(list(self.data.glob('*.tmp')))

    def test_corrupt_backup_recovers_defaults_and_invalid_executable_is_visible(self):
        runtime.SETTINGS.write_text('{bad',encoding='utf-8')
        runtime.SETTINGS.with_suffix('.json.bak').write_text('[]',encoding='utf-8')
        self.assertEqual(runtime.read_settings(),{})
        self.assertTrue(runtime.latex_status()['warning'])
        runtime.SETTINGS.write_text(json.dumps({'xelatex_path':str(self.home/'missing/xelatex.exe')}),encoding='utf-8')
        self.assertFalse(runtime.latex_status()['available'])

    def test_pdf_limits_and_encryption(self):
        from backend.assets import validate_upload
        for count, encrypted in [(0,False),(201,False),(1,True)]:
            writer=PdfWriter()
            for _ in range(count):writer.add_blank_page(100,100)
            if encrypted:writer.encrypt('password')
            buffer=io.BytesIO();writer.write(buffer)
            with self.assertRaises(ValueError):validate_upload(buffer.getvalue(),'.pdf')

    def test_truncated_image_and_wrong_extension_are_rejected(self):
        from backend.assets import validate_upload
        buffer=io.BytesIO();Image.new('RGB',(20,20)).save(buffer,format='PNG')
        with self.assertRaises(ValueError):validate_upload(buffer.getvalue(),'.jpg')
        with self.assertRaises(ValueError):validate_upload(buffer.getvalue()[:30],'.png')

    def test_large_image_is_rejected_before_decode(self):
        from backend.assets import validate_upload
        fake=__import__('unittest').mock.MagicMock()
        fake.__enter__.return_value=fake
        fake.format='PNG';fake.width=10_000;fake.height=10_000
        with patch('PIL.Image.open',return_value=fake):
            with self.assertRaisesRegex(ValueError,'5000 万像素'):validate_upload(b'header','.png')
        fake.load.assert_not_called()

    def test_deleted_source_draft_is_preserved_and_save_as_new_works(self):
        question=self.create();draft_id=str(uuid.uuid4())
        self.db.save_draft(draft_id,0,question['id'],question['revision'],self.draft(question),position_mode='keep')
        self.db.delete_question(question['id'],question['revision'])
        with self.assertRaises(RuntimeError):self.db.publish_draft(draft_id,1,payload(),False)
        self.assertEqual(self.db.get_draft(draft_id)['revision'],1)
        result,changed=self.db.publish_draft(draft_id,1,payload(),True)
        self.assertTrue(changed)
        self.assertNotEqual(result['question']['id'],question['id'])

    def test_paper_failure_keeps_success_and_removes_staging(self):
        question=self.create();self.db.pool_add(question['id'])
        snapshot,assets=self.db.paper_snapshot('manual',[question['id']]);manager=papers.PaperManager(self.db)
        with patch.object(papers,'compile_tex',return_value=b'%PDF'):manager._run('manual',snapshot,assets)
        pointer=self.home/'output/papers/current.json';before=pointer.read_bytes()
        with patch.object(papers,'compile_tex',side_effect=RuntimeError('injected failure')):manager._run('manual',snapshot,assets)
        self.assertEqual(pointer.read_bytes(),before)
        self.assertTrue(manager.status()['available'])
        self.assertEqual(manager.status()['state'],'failed')
        self.assertFalse(list((self.home/'output/papers/versions').glob('.building-*')))

    def test_failed_export_keeps_pointer_and_cleans_staging(self):
        self.create()
        manager=latex_service.ExportManager(self.db)
        with patch.object(latex_service,'compile_tex',return_value=b'%PDF'):
            manager._run_export('gaoyi-second')
        pointer=self.home/'output/current-gaoyi-second.json';before=pointer.read_bytes()
        with patch.object(latex_service,'compile_tex',side_effect=latex_service.LatexError('injected failure')):
            manager._run_export('gaoyi-second')
        self.assertEqual(pointer.read_bytes(),before)
        self.assertTrue(manager.status('gaoyi-second')['available'])
        self.assertEqual(manager.status('gaoyi-second')['state'],'failed')
        self.assertFalse(list((self.home/'output/versions/gaoyi-second').glob('.building-*')))

    def test_closed_draft_cannot_resurrect_and_retry_is_idempotent(self):
        draft_id=str(uuid.uuid4());content={'form':payload(),'source_rows':[]}
        first=self.db.save_draft(draft_id,0,None,None,content,position_mode='move',target_order_revision=1)
        retry=self.db.save_draft(draft_id,0,None,None,content,position_mode='move',target_order_revision=1)
        self.assertEqual(first,retry)
        self.db.discard_draft(draft_id,1)
        with self.assertRaises(RuntimeError):self.db.save_draft(draft_id,0,None,None,content)
