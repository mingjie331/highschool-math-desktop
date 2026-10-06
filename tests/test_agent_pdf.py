import asyncio
import io
import threading
import json
import uuid
import sqlite3
from unittest.mock import patch
from pypdf import PdfWriter
from tests.support import IsolatedCase,catalog
from backend.agent import AgentManager


class ImportRepairTests(IsolatedCase):
    def setUp(self):
        super().setUp();self.manager=AgentManager(self.db);self.session=self.manager.create_session()
        from PIL import Image
        output=io.BytesIO();Image.new('RGB',(100,100),'white').save(output,'PNG')
        self.image=self.manager.attach(self.session['id'],'测试.png',output.getvalue());self.addCleanup(self.manager.stop)
    def task(self):return self.manager.create_task(self.session['id'],{'attachment_ids':[self.image['id']]})
    def candidate(self,**changes):
        return {'type':'fill','question_tex':'计算 $1+1$。','answer_tex':'','solution_tex':'','original_number':'19',
            'collection_code':'gaoyi-first','point_code':'2.1','regions':[{'image_id':self.image['id'],'rect':[0,0,1,1]}],**changes}
    def test_complete_original_solution_does_not_call_solver(self):
        task = self.task()
        iid = self.manager.accept_candidates(task['id'], [self.candidate(
            answer_tex='2', solution_tex='$1+1=2$', answer_origin='original', solution_origin='original')])[0]
        with patch.object(self.manager.provider, 'json', side_effect=AssertionError('不要重解原解析')), patch.object(self.manager, 'compile_item'):
            asyncio.run(self.manager._process_item(iid, threading.Event()))
        self.assertEqual(self.manager.get_item(iid)['state'], 'ready')

    def test_pdf_upload_preserves_document_and_pages(self):
        output = io.BytesIO(); writer = PdfWriter()
        for _ in range(2): writer.add_blank_page(width=595, height=842)
        writer.write(output)
        document = self.manager.attach(self.session['id'], '卷子.pdf', output.getvalue())
        self.assertEqual(document['page_count'], 2)
        self.assertEqual([p['page_number'] for p in document['pages']], [1, 2])
        task = self.manager.create_task(self.session['id'], {'attachment_ids': [p['id'] for p in document['pages']]})
        self.assertEqual(task['payload']['page_count'], 2)

    def test_file_name_is_default_source(self):
        task = self.task()
        iid = self.manager.accept_candidates(task['id'], [self.candidate(original_number='19')])[0]
        source = self.manager.get_item(iid)['form']['sources']['origins'][0]
        self.assertEqual(source['title'], '测试')
        self.assertEqual(source['original_number'], '19')

    def test_figure_requires_confirmation_and_hash_changes(self):
        task = self.task()
        iid = self.manager.accept_candidates(task['id'], [self.candidate(answer_tex='2', solution_tex='解析', figures=[
            {'id':'f','field':'solution_tex','image_id':self.image['id'],'rect':[.1,.1,.9,.9]}])])[0]
        with patch.object(self.manager, 'compile_item'):
            item = self.manager.validate_item(iid)
            self.assertEqual(item['state'], 'needs_review')
            item = self.manager.update_item(iid, item['revision'], {'figures_confirmed':True})
            self.assertEqual(self.manager.validate_item(iid)['state'], 'ready')

    def test_pausing_worker_clears_active_item_state(self):
        task = self.task(); iid = self.manager.accept_candidates(task['id'], [self.candidate()])[0]
        item = self.manager.get_item(iid)
        self.manager._set_item(iid, 'solving', item['details'], expected=item['revision'])
        self.manager._settle_items(task['id'], '网络暂停')
        self.assertEqual(self.manager.get_item(iid)['state'], 'needs_review')

    def pdf(self,pages=1):
        output=io.BytesIO();writer=PdfWriter()
        for _ in range(pages):writer.add_blank_page(width=20,height=20)
        writer.write(output);return output.getvalue()

    def test_pdf_page_boundaries_and_mixed_batch_limit(self):
        document=self.manager.attach(self.session['id'],'二十页.pdf',self.pdf(20))
        self.manager.create_task(self.session['id'],{'attachment_ids':[p['id'] for p in document['pages']]})
        with self.assertRaises(ValueError):self.manager.create_task(self.session['id'],{'attachment_ids':[self.image['id'],*[p['id'] for p in document['pages']]]})
        before=len(self.manager.get_session(self.session['id'])['documents'])
        with self.assertRaises(ValueError):self.manager.attach(self.session['id'],'超限.pdf',self.pdf(21))
        self.assertEqual(len(self.manager.get_session(self.session['id'])['documents']),before)

    def test_invalid_pdf_and_size_fail_without_residual_files(self):
        for value in [b'',b'not PDF',self.pdf()[:-15],b'x'*(32*1024*1024+1)]:
            with self.assertRaises(ValueError):self.manager.attach(self.session['id'],'假.pdf',value)
        self.assertFalse((self.manager.store.directory/'documents').exists())

    def test_password_pdf_rejected(self):
        writer=PdfWriter();writer.add_blank_page(width=20,height=20);writer.encrypt('secret');out=io.BytesIO();writer.write(out)
        with self.assertRaises(ValueError):self.manager.attach(self.session['id'],'密码.pdf',out.getvalue())

    def test_pdf_database_failure_cleans_rendered_pages(self):
        import contextlib
        @contextlib.contextmanager
        def failure():raise RuntimeError('database failure');yield
        with patch.object(self.db,'transaction',failure):
            with self.assertRaises(RuntimeError):self.manager.attach(self.session['id'],'回滚.pdf',self.pdf())
        self.assertFalse(list((self.manager.store.directory/'documents').glob('*')))
        self.assertEqual(len(self.manager.get_session(self.session['id'])['attachments']),1)

    def test_number_parser_and_natural_selection_conflict(self):
        from backend.agent_index import parse_numbers,natural_numbers
        self.assertEqual(parse_numbers('1,3,17–19'),['1','3','17','18','19'])
        self.assertEqual(natural_numbers('提取第17至19题'),['17','18','19'])
        self.assertEqual(natural_numbers('提取第十九题'),['19'])
        for value in ['0','19-17','1-51','任意题']:
            with self.assertRaises(ValueError):parse_numbers(value)
        with self.assertRaises(ValueError):self.manager.create_task(self.session['id'],{'attachment_ids':[self.image['id']], 'question_numbers':'19','instruction':'提取第18题'})

    def test_pairing_keeps_same_number_exams_separate(self):
        q=self.manager.attach(self.session['id'],'同套_试卷.pdf',self.pdf())
        a=self.manager.attach(self.session['id'],'同套_答案.pdf',self.pdf())
        other=self.manager.attach(self.session['id'],'其他试卷.pdf',self.pdf())
        ids=[p['id'] for d in [q,a,other] for p in d['pages']]
        with self.assertRaises(ValueError):self.manager.create_task(self.session['id'],{'attachment_ids':ids,'question_numbers':'19'})
        task=self.manager.create_task(self.session['id'],{'attachment_ids':ids,'question_numbers':'19','target_document_id':q['id']})
        groups=task['payload']['document_groups'];self.assertEqual(groups[q['id']],groups[a['id']]);self.assertNotEqual(groups[q['id']],groups[other['id']])

    def test_mapping_rejects_image_id_outside_current_request(self):
        mapping={'view-1':{'image_id':self.image['id'],'rect':[.5,0,1,1]}}
        region=self.manager._map_region({'image_id':'view-1','rect':[0,.2,.5,.8]},mapping)
        self.assertEqual(region['rect'],[.5,.2,.75,.8])
        with self.assertRaises(ValueError):self.manager._map_region({'image_id':self.image['id'],'rect':[0,0,1,1]},mapping)

    def test_replace_figure_keeps_one_reference_and_invalidates_confirmation(self):
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate(figures=[{'id':'f','field':'question_tex','image_id':self.image['id'],'rect':[.1,.1,.5,.5]}])])[0]
        item=self.manager.get_item(iid);old=item['details']['figures'][0]['asset_path']
        changed=self.manager.crop_figure(iid,item['revision'],{'image_id':self.image['id'],'rect':[.05,.05,.6,.6]},'question_tex','f')
        self.assertEqual(len(changed['details']['figures']),1);self.assertNotIn(old,changed['form']['question_tex']);self.assertFalse(changed['details']['figures_confirmed'])

    def test_generation_truncation_has_bounded_retry_and_keeps_original(self):
        from backend.deepseek import ProviderError
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate(answer_tex='原答案',answer_origin='original')])[0]
        limits=[]
        async def fail(*args,**kwargs):limits.append(kwargs['max_tokens']);raise ProviderError('截断',code='output_truncated',max_tokens=kwargs['max_tokens'])
        with patch.object(self.manager.provider,'json',side_effect=fail):asyncio.run(self.manager._process_item(iid,threading.Event()))
        item=self.manager.get_item(iid);self.assertEqual(limits,[32000,64000]);self.assertEqual(item['state'],'needs_review')
        self.assertEqual(item['form']['answer_tex'],'原答案');self.assertEqual(item['details']['stage_error']['stage'],'completion')

    def test_schema_6_migration_is_idempotent_and_preserves_draft(self):
        task=self.task();self.manager.accept_candidates(task['id'],[self.candidate()]);before=self.db.list_drafts()
        with self.db.transaction() as conn:conn.execute("UPDATE metadata SET value='6' WHERE key='schema_version'")
        self.db.initialize();count=len(list((self.data/'backups').glob('*.sqlite3')));self.db.initialize()
        self.assertEqual(before,self.db.list_drafts());self.assertEqual(count,len(list((self.data/'backups').glob('*.sqlite3'))))
        from contextlib import closing
        with closing(self.db.connect()) as conn:self.assertEqual(conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],str(catalog.SCHEMA_VERSION))

    def test_targeted_index_extraction_filters_other_answer_table_questions(self):
        from backend.agent_index import index_and_extract
        task=self.manager.create_task(self.session['id'],{'attachment_ids':[self.image['id']],'question_numbers':'19','pipeline_version':2})
        calls=[]
        async def response(messages,**kwargs):
            calls.append(messages)
            if '只建立' in messages[0]['content']:
                return {'segments':[{'number':'18','role':'question','regions':[{'image_id':'view-1','rect':[0,0,1,.4]}]},
                    {'number':'19','role':'question','regions':[{'image_id':'view-1','rect':[0,.4,1,1]}]}]},'mock'
            return {'questions':[self.candidate(original_number='18',regions=[{'image_id':'view-1','rect':[0,0,1,1]}]),
                self.candidate(original_number='19',answer_tex='2',solution_tex='原解析',regions=[{'image_id':'view-1','rect':[0,0,1,1]}])]},'mock'
        with patch.object(self.manager.provider,'json',side_effect=response):
            ids=asyncio.run(index_and_extract(self.manager,task['id'],threading.Event()))
            again=asyncio.run(index_and_extract(self.manager,task['id'],threading.Event()))
        self.assertEqual(ids,again);self.assertEqual(len(calls),2);self.assertEqual(self.manager.get_item(ids[0])['details']['original_number'],'19')

    def test_answer_only_pdf_does_not_invent_stem(self):
        from backend.agent_index import index_and_extract
        task=self.manager.create_task(self.session['id'],{'attachment_ids':[self.image['id']],'pipeline_version':2})
        async def answer(*args,**kwargs):return {'segments':[{'number':'19','role':'solution','regions':[{'image_id':'view-1','rect':[0,0,1,1]}]}]},'mock'
        with patch.object(self.manager.provider,'json',side_effect=answer):
            self.assertEqual(asyncio.run(index_and_extract(self.manager,task['id'],threading.Event())),[])
        self.assertEqual(len(self.manager.get_task(task['id'])['failures']),1)
        self.assertEqual(len(self.db.list_drafts()),0)

    def test_one_invalid_candidate_does_not_abort_other_questions(self):
        from backend.agent_index import index_and_extract
        task=self.manager.create_task(self.session['id'],{'attachment_ids':[self.image['id']],'pipeline_version':2})
        async def response(messages,**kwargs):
            if '只建立' in messages[0]['content']:return {'segments':[{'number':str(n),'role':'question','regions':[{'image_id':'view-1','rect':[0,0,1,1]}]} for n in [1,2]]},'mock'
            number=json.loads(messages[1]['content'][0]['text'])['original_number']
            return {'questions':[] if number=='1' else [self.candidate(original_number='2',regions=[{'image_id':'view-1','rect':[0,0,1,1]}])]},'mock'
        with patch.object(self.manager.provider,'json',side_effect=response):ids=asyncio.run(index_and_extract(self.manager,task['id'],threading.Event()))
        self.assertEqual(len(ids),1);self.assertEqual(self.manager.get_item(ids[0])['state'],'pending');self.assertEqual(len(self.manager.get_task(task['id'])['failures']),1)

    def test_generation_from_existing_solution_uses_no_reasoning(self):
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate(solution_tex='原解析 $1+1=2$',solution_origin='original')])[0]
        options=[]
        async def response(*args,**kwargs):options.append(kwargs);return {'answer_tex':'2','solution_tex':''},'mock'
        with patch.object(self.manager.provider,'json',side_effect=response),patch.object(self.manager,'compile_item'):
            asyncio.run(self.manager._process_item(iid,threading.Event()))
        self.assertFalse(options[0]['thinking']);self.assertEqual(options[0]['max_tokens'],4000)
        item=self.manager.get_item(iid);self.assertEqual(item['form']['solution_tex'],'原解析 $1+1=2$');self.assertEqual(item['details']['answer_origin'],'original')

    def test_common_table_commands_and_text_blanks_compile_contract(self):
        from backend.agent_tex import normalize_tex_fragment,validate_agent_tex
        text=normalize_tex_fragment('求 $x_0$ 的值：____。')
        self.assertIn('x_0',text);self.assertIn(r'\underline{\hspace{2em}}',text)
        validate_agent_tex({'question_tex':r'$x\geqslant0$，\begin{tabular}{cc}\hline\multirow{2}{*}{甲}&乙\\\hline\end{tabular}'},set())

    def test_unclassified_model_result_is_not_ready_until_classified(self):
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate(collection_code='misc',point_code='6.1',answer_tex='2',solution_tex='原解析')])[0]
        async def classify(*args,**kwargs):return {'collection_code':'gaoyi-first','point_code':'1.1','reason':'集合运算'},'mock'
        with patch.object(self.manager.provider,'json',side_effect=classify),patch.object(self.manager,'compile_item'):
            asyncio.run(self.manager._process_item(iid,threading.Event()))
        item=self.manager.get_item(iid);self.assertEqual(item['state'],'ready');self.assertTrue(item['details']['stages']['classification']['complete'])

    def test_named_pdf_alias_matches_pair_but_not_different_exam(self):
        from backend.agent_index import named_documents
        docs={'a':{'filename':'数学_九师联盟2026_试卷.pdf'},'b':{'filename':'数学_九师联盟2026_答案.pdf'},'c':{'filename':'四川百师联盟2026.pdf'}}
        self.assertEqual(set(named_documents('提取九师联盟第十九题',docs)),{'a','b'})

    def test_candidate_boxes_cannot_replace_server_source_context(self):
        from backend.agent_index import extract_one
        task=self.task()
        value=self.candidate(regions=[{'image_id':'invented','rect':[0,0,0,0]}])
        async def reply(*args,**kwargs):return value,'mock'
        with patch.object(self.manager.provider,'json',side_effect=reply):result=asyncio.run(extract_one(self.manager,task['id'],'19',[{'image_id':self.image['id'],'rect':[0,0,1,1]}],[],threading.Event()))
        self.assertEqual(result['regions'][0]['image_id'],self.image['id'])

    def test_original_solution_auth_failure_keeps_recognized_stem(self):
        from backend.deepseek import ProviderError
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate(question_tex='原题干已经识别',
            regions=[{'image_id':self.image['id'],'rect':[0,0,1,1],'role':'solution'}],uncertainties=['原解析区域已定位，但完整步骤未提取，请重新识别此题'])])[0]
        with patch.object(self.manager.provider,'json',side_effect=ProviderError('账户暂停',401)):
            with self.assertRaises(ProviderError):asyncio.run(self.manager._process_item(iid,threading.Event()))
        item=self.manager.get_item(iid);self.assertEqual(item['form']['question_tex'],'原题干已经识别');self.assertEqual(item['state'],'needs_review')
        self.assertEqual(item['details']['stage_error']['stage'],'original_solution')

    def test_edit_during_original_extraction_preserves_edit_and_leaves_active_state(self):
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate(regions=[{'image_id':self.image['id'],'rect':[0,0,1,1],'role':'solution'}],
            uncertainties=['原解析区域已定位，但完整步骤未提取，请重新识别此题'])])[0]
        async def response(*args,**kwargs):
            item=self.manager.get_item(iid);draft=self.db.get_draft(item['draft_id']);content=draft['content'];content['form']['question_tex']='人工修正'
            self.db.save_draft(item['draft_id'],draft['revision'],None,None,content)
            return {'answer_tex':'2','solution_tex':'模型旧解析'},'mock'
        with patch.object(self.manager.provider,'json',side_effect=response):asyncio.run(self.manager._process_item(iid,threading.Event()))
        item=self.manager.get_item(iid);self.assertEqual(item['form']['question_tex'],'人工修正');self.assertEqual(item['state'],'needs_review');self.assertEqual(item['form']['solution_tex'],'')

    def test_original_solution_missing_subquestion_is_recovered_without_solving(self):
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate(type='long',question_tex='（1）求 $x$。\n（2）求 $y$。',answer_tex='2,3',
            solution_tex='（1）$x=2$。',answer_origin='original',solution_origin='original',regions=[{'image_id':self.image['id'],'rect':[0,0,1,1],'role':'solution'}])])[0]
        requests=[]
        async def extract(messages,**kwargs):requests.append(messages);return {'solution_tex':'（2）$y=3$。'},'mock'
        with patch.object(self.manager.provider,'json',side_effect=extract),patch.object(self.manager,'compile_item'):
            asyncio.run(self.manager._process_item(iid,threading.Event()))
        item=self.manager.get_item(iid);self.assertEqual(item['state'],'ready');self.assertIn('（1）',item['form']['solution_tex']);self.assertIn('（2）',item['form']['solution_tex'])
        self.assertIn('只转写',requests[0][0]['content']);self.assertEqual(item['details']['solution_origin'],'original')
