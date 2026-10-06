import asyncio
import io
import threading
import uuid
from unittest.mock import patch
from tests.support import IsolatedCase
from backend.agent import AgentManager


class Import132Tests(IsolatedCase):
    def setUp(self):
        super().setUp();self.manager=AgentManager(self.db);self.addCleanup(self.manager.stop)
        from PIL import Image
        out=io.BytesIO();Image.new('RGB',(100,100),'white').save(out,'PNG')
        self.session=self.manager.create_session();self.image=self.manager.attach(self.session['id'],'卷子.png',out.getvalue())
        self.task=self.manager.create_task(self.session['id'],{'attachment_ids':[self.image['id']], 'input_regions':[{'image_id':self.image['id'],'rect':[.1,.2,.8,.9]}]})
    def candidate(self,**kwargs):
        return {'type':'long','question_tex':'求值。（1）求 $x$；（2）求 $y$。','answer_tex':'（1）2；（2）3','solution_tex':'（1）$x=2$；（2）$y=3$。','collection_code':'gaoyi-first','point_code':'1.1','original_number':'19','regions':[{'image_id':self.image['id'],'rect':[.2,.3,.7,.8]}],**kwargs}
    def item(self):return self.manager.get_item(self.manager.accept_candidates(self.task['id'],[self.candidate()])[0])
    def test_render_subparts_only_outside_math_and_environments(self):
        from backend.tex_layout import subpart_paragraphs
        text=r'已知 $P(1)$。\begin{aligned}x=(1)\\y=(2)\end{aligned}（1）求值；（2）证明；（3）讨论。'
        result=subpart_paragraphs(text)
        self.assertEqual(result.count(r'\par'),3);self.assertEqual(subpart_paragraphs(result),result)
        self.assertIn(r'x=(1)\\y=(2)',result)
        self.assertEqual(subpart_paragraphs('括号（1）是标注。'), '括号（1）是标注。')
    def test_empty_candidate_never_saves_draft(self):
        for stem in ['', '  ', '[FIGURE:f]', r'\par\includegraphics{assets/a.png}', '此题提取未完成，请重新识别']:
            with self.assertRaises(ValueError):self.manager.accept_candidates(self.task['id'],[self.candidate(question_tex=stem)])
        self.assertEqual(self.db.list_drafts(),[])
    def test_delete_atomic_retry_and_late_worker_rejected(self):
        item=self.item();request=str(uuid.uuid4())
        result=self.manager.delete_candidate(item['id'],item['revision'],item['draft_revision'],request)
        self.assertEqual(result,self.manager.delete_candidate(item['id'],item['revision'],item['draft_revision'],request))
        self.assertEqual(self.db.list_drafts(),[]);self.assertEqual(self.manager.workbench(review_stage='review')['total'],0)
        with self.assertRaises(RuntimeError):self.manager._set_item(item['id'],'ready',item['details'])
        with self.assertRaises(RuntimeError):self.manager._replace_item(item['id'],item['revision'],self.candidate())
        self.assertEqual(self.manager.get_item(item['id'])['form'],{})
    def test_delete_conflict_preserves_content(self):
        item=self.item()
        with self.assertRaises(RuntimeError):self.manager.delete_candidate(item['id'],item['revision']+1,item['draft_revision'],str(uuid.uuid4()))
        self.assertEqual(self.manager.get_item(item['id'])['form']['question_tex'],item['form']['question_tex'])
    def test_crop_boundary_survives_extraction(self):
        from backend.agent_index import extract_one
        sent=[]
        async def response(*args,**kwargs):return self.candidate(),'mock'
        original=self.manager._visual_blocks
        def capture(task,regions=None):sent.extend(regions);return original(task,regions)
        with patch.object(self.manager.provider,'json',side_effect=response),patch.object(self.manager,'_visual_blocks',side_effect=capture):
            value=asyncio.run(extract_one(self.manager,self.task['id'],'19',self.candidate()['regions'],[],threading.Event()))
        self.assertEqual(sent[0]['rect'],[.1,.2,.8,.9]);self.assertEqual(value['regions'][0]['rect'],[.1,.2,.8,.9])
    def test_failed_index_extraction_is_task_record_not_draft_and_retry_only_failed(self):
        from backend.agent_index import index_and_extract
        async def index(*args,**kwargs):return {'segments':[{'number':n,'role':'question','regions':[{'image_id':'view-1','rect':[0,0,1,1]}]} for n in ['18','19']]},'mock'
        calls=[]
        async def extract(manager,tid,number,*args):
            calls.append(number)
            if number=='19' and calls.count(number)==1:raise ValueError('提取失败')
            return self.candidate(original_number=number)
        with patch.object(self.manager.provider,'json',side_effect=index),patch('backend.agent_index.extract_one',side_effect=extract):
            ids=asyncio.run(index_and_extract(self.manager,self.task['id'],threading.Event()))
            self.assertEqual(len(ids),1);self.assertEqual(len(self.db.list_drafts()),1)
            self.assertEqual(len(self.manager.get_task(self.task['id'])['failures']),1)
            ids=asyncio.run(index_and_extract(self.manager,self.task['id'],threading.Event()))
        self.assertEqual(calls,['18','19','19']);self.assertEqual(len(ids),2)
        self.assertEqual(self.manager.get_task(self.task['id'])['failures'],[])

    def test_delete_published_refused(self):
        item=self.item()
        with patch.object(self.manager,'compile_item'):item=self.manager.confirm_review(item['id'],item['revision'],str(uuid.uuid4()))
        self.manager.publish_batch(str(uuid.uuid4()),[{'id':item['id'],'revision':item['revision']}])
        with self.assertRaises(RuntimeError):self.manager.delete_candidate(item['id'],item['revision'],1,str(uuid.uuid4()))
        self.assertEqual(self.db.catalog()['total'],628)
    def test_delete_removes_checkpoint_and_failed_retry_cannot_restore(self):
        item=self.item();payload=self.manager.store.task(self.task['id'])['payload']
        payload['question_checkpoint']={'index':[],'item_ids':[item['id']],'completed':{'images:19':item['id']}}
        from backend.agent_store import encode
        self.manager.store.task_update(self.task['id'],payload_json=encode(payload))
        self.manager.delete_candidate(item['id'],item['revision'],item['draft_revision'],str(uuid.uuid4()))
        checkpoint=self.manager.store.task(self.task['id'])['payload']['question_checkpoint']
        self.assertEqual(checkpoint['item_ids'],[]);self.assertEqual(checkpoint['completed'],{});self.assertEqual(checkpoint['deleted_keys'],['images:19'])
    def test_legacy_empty_placeholder_hidden_but_manual_edit_not_hidden(self):
        from backend.agent_store import encode
        ids=self.manager.accept_candidates(self.task['id'],[self.candidate(question_tex='')],_allow_empty=True)
        item=self.manager.get_item(ids[0]);details=item['details'];details['stage_error']={'stage':'recognition','message':'失败'}
        self.manager._set_item(item['id'],'needs_review',details)
        self.assertEqual(self.manager.workbench(review_stage='review')['total'],0)
        self.assertEqual(len(self.manager.get_task(self.task['id'])['failures']),1)
        item=self.manager.get_item(item['id']);self.manager.update_item(item['id'],item['revision'],{'form':{'question_tex':'人工题干'}})
        self.assertEqual(self.manager.workbench(review_stage='review')['total'],1)
        self.assertEqual(self.manager.get_task(self.task['id'])['failures'],[])
    def test_broken_figure_keeps_recognized_stem(self):
        value=self.candidate(question_tex='已识别正文。[FIGURE:missing]')
        item=self.manager.get_item(self.manager.accept_candidates(self.task['id'],[value])[0])
        self.assertIn('已识别正文',item['form']['question_tex']);self.assertTrue(item['details']['uncertainties'])
    def test_pdf_self_pair_rejected_and_combined_default_accepted(self):
        from pypdf import PdfWriter
        out=io.BytesIO();w=PdfWriter();w.add_blank_page(width=30,height=30);w.write(out)
        doc=self.manager.attach(self.session['id'],'卷子_试卷+答案.pdf',out.getvalue());ids=[p['id'] for p in doc['pages']]
        payload={'attachment_ids':ids,'question_numbers':'18,19','input_regions':[{'image_id':ids[0],'rect':[.1,.2,.8,.9]}]}
        task=self.manager.create_task(self.session['id'],payload);self.assertEqual(task['payload']['resolved_pairs'],[])
        with self.assertRaisesRegex(ValueError,'自身'):self.manager.create_task(self.session['id'],{**payload,'document_pairs':[{'question_document_id':doc['id'],'answer_document_id':doc['id']}]})

    def test_existing_breaks_coordinates_and_citations_not_reformatted(self):
        from backend.tex_layout import subpart_paragraphs
        for text in [r'点 P(1)，Q(2)',r'由（1）得（2）',r'\begin{enumerate}\item (1) 求值\item (2) 求值\end{enumerate}']:
            self.assertEqual(subpart_paragraphs(text),text)
        text=r'（1）求值；\par （2）证明。';self.assertEqual(subpart_paragraphs(subpart_paragraphs(text)),subpart_paragraphs(text))
    def test_old_successful_render_approval_invalidated(self):
        item=self.item()
        with patch.object(self.manager,'compile_item'):item=self.manager.confirm_review(item['id'],item['revision'],str(uuid.uuid4()))
        with patch('backend.agent.RENDER_VERSION',99):self.assertEqual(self.manager.get_item(item['id'])['review_stage'],'review')
    def test_deletion_is_rolled_back_if_task_update_fails(self):
        import sqlite3
        item=self.item()
        with self.db.transaction() as c:c.execute("CREATE TRIGGER fail_delete_task BEFORE UPDATE ON ai_tasks BEGIN SELECT RAISE(ABORT,'fail task'); END")
        with self.assertRaises(sqlite3.DatabaseError):self.manager.delete_candidate(item['id'],item['revision'],item['draft_revision'],str(uuid.uuid4()))
        self.assertEqual(self.manager.get_item(item['id'])['form']['question_tex'],item['form']['question_tex']);self.assertEqual(len(self.db.list_drafts()),1)

    def test_delete_survives_reconstructed_manager(self):
        item=self.item();self.manager.delete_candidate(item['id'],item['revision'],item['draft_revision'],str(uuid.uuid4()))
        restarted=AgentManager(self.db)
        self.assertEqual(restarted.get_item(item['id'])['review_stage'],'deleted');self.assertEqual(restarted.workbench(review_stage='review')['total'],0)
        self.assertEqual(self.db.list_drafts(),[]);restarted.stop()

    def test_split_failure_empty_draft_hidden_without_specific_stage_error(self):
        original=self.item();groups=[[{'image_id':self.image['id'],'rect':[.1,.2,.8,.9]}]]
        task=self.manager.restructure(self.task['id'],[{'id':original['id'],'revision':original['revision']}],groups,_enqueue=False)
        child=next(i for i in task['items'] if i['state']!='skipped')
        self.manager._settle_items(self.task['id'],'连接失败')
        self.assertEqual(self.manager.get_item(child['id'])['review_stage'],'failed')
        self.assertEqual(self.manager.workbench(review_stage='review')['total'],0)
