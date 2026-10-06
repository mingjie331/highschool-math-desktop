import io
import threading
import uuid
from unittest.mock import patch
from tests.support import IsolatedCase
from backend.agent import AgentManager


class ReviewTests(IsolatedCase):
    def setUp(self):
        super().setUp();self.manager=AgentManager(self.db);self.session=self.manager.create_session()
        from PIL import Image
        out=io.BytesIO();Image.new('RGB',(50,50),'white').save(out,'PNG')
        self.image=self.manager.attach(self.session['id'],'核对测试.png',out.getvalue());self.addCleanup(self.manager.stop)
    def item(self,stem='计算 $1+1$。'):
        task=self.manager.create_task(self.session['id'],{'attachment_ids':[self.image['id']]})
        iid=self.manager.accept_candidates(task['id'],[{'type':'fill','question_tex':stem,'answer_tex':'2','solution_tex':'$1+1=2$。',
            'collection_code':'gaoyi-first','point_code':'1.1','original_number':'19','regions':[{'image_id':self.image['id'],'rect':[0,0,1,1]}]}])[0]
        return self.manager.get_item(iid)
    def confirm(self,item):
        with patch.object(self.manager,'compile_item'):return self.manager.confirm_review(item['id'],item['revision'],str(uuid.uuid4()))
    def test_compiled_candidate_still_requires_human_review(self):
        item=self.item()
        with patch.object(self.manager,'compile_item'):item=self.manager.validate_item(item['id'])
        self.assertEqual(item['review_stage'],'review')
        with self.assertRaises(RuntimeError):self.manager.publish(item['task_id'],str(uuid.uuid4()),[{'id':item['id'],'revision':item['revision']}])
    def test_confirmation_and_return_are_persistent(self):
        item=self.confirm(self.item());self.assertEqual(item['review_stage'],'publish');self.assertTrue(item['reviewed_at'])
        returned=self.manager.return_review(item['id'],item['revision']);self.assertEqual(returned['review_stage'],'review')
    def test_cross_task_publish_is_atomic_and_idempotent(self):
        items=[self.confirm(self.item(stem)) for stem in ['计算 $1+1$。','计算 $2+2$。']]
        request=str(uuid.uuid4());selection=[{'id':i['id'],'revision':i['revision']} for i in items]
        result=self.manager.publish_batch(request,selection)
        self.assertEqual(result,self.manager.publish_batch(request,selection));self.assertEqual(self.db.catalog()['total'],629)
    def test_user_edit_invalidates_confirmation(self):
        item=self.confirm(self.item());item=self.manager.update_item(item['id'],item['revision'],{'form':{'answer_tex':'3'}})
        self.assertEqual(item['review_stage'],'review');self.assertIsNone(item['reviewed_hash'])
    def test_batch_rejects_unreviewed_without_partial_write(self):
        items=[self.confirm(self.item()),self.item('计算 $2+2$。')]
        with self.assertRaises(RuntimeError):self.manager.publish_batch(str(uuid.uuid4()),[{'id':i['id'],'revision':i['revision']} for i in items])
        self.assertEqual(self.db.catalog()['total'],627)

    def test_confirmation_retry_returns_same_result_without_recompiling(self):
        item=self.item();request=str(uuid.uuid4())
        with patch.object(self.manager,'compile_item') as compile:
            first=self.manager.confirm_review(item['id'],item['revision'],request)
            second=self.manager.confirm_review(item['id'],item['revision'],request)
        self.assertEqual(first['revision'],second['revision']);self.assertEqual(compile.call_count,1)

    def test_draft_edit_during_compile_is_kept_and_conflicts(self):
        item=self.item()
        def compile(current,*args):
            draft=self.db.get_draft(item['draft_id']);draft['content']['form']['question_tex']='人工修改'
            self.db.save_draft(item['draft_id'],draft['revision'],None,None,draft['content'])
        with patch.object(self.manager,'compile_item',side_effect=compile):
            with self.assertRaises(RuntimeError):self.manager.confirm_review(item['id'],item['revision'],str(uuid.uuid4()))
        result=self.manager.get_item(item['id']);self.assertEqual(result['form']['question_tex'],'人工修改');self.assertIsNone(result['reviewed_hash'])

    def test_resource_change_after_review_invalidates_publish(self):
        from tests.support import latex_service
        item=self.confirm(self.item())
        template=self.home/'template.tex';template.write_text('different')
        with patch.object(latex_service,'SOURCE_PREAMBLE',template):
            self.assertEqual(self.manager.get_item(item['id'])['review_stage'],'review')
            with self.assertRaises(RuntimeError):self.manager.publish_batch(str(uuid.uuid4()),[{'id':item['id'],'revision':item['revision']}])

    def test_unresolved_conflict_and_missing_number_are_locatable(self):
        item=self.item();item=self.manager.update_item(item['id'],item['revision'],{'answer_conflict':True,'original_number':''})
        with patch.object(self.manager,'compile_item'):
            with self.assertRaises(RuntimeError) as error:self.manager.confirm_review(item['id'],item['revision'],str(uuid.uuid4()))
        sections={i['section'] for i in error.exception.detail['issues']};self.assertTrue({'answer','classification'}<=sections)

    def test_source_edit_preserves_page_provenance_and_invalidates_review(self):
        item=self.confirm(self.item());pages=item['form']['sources']['ai_import']['pages']
        changed=self.manager.update_item(item['id'],item['revision'],{'source_title':'人工题源'})
        self.assertEqual(changed['form']['sources']['ai_import']['pages'],pages);self.assertEqual(changed['form']['sources']['origins'][0]['title'],'人工题源')
        self.assertEqual(changed['review_stage'],'review')

    def test_model_tools_cannot_set_review_fields(self):
        item=self.item()
        for field in ['reviewed_hash','reviewed_at','review_stage']:
            with self.assertRaises(ValueError):self.manager.update_item(item['id'],item['revision'],{field:'approved'})

    def test_compact_queue_counts_filters_and_order(self):
        older=self.item('旧任务题干');newer=self.item('新任务题干');self.confirm(newer)
        queue=self.manager.workbench();self.assertEqual(queue['counts']['review'],1);self.assertEqual(queue['counts']['publish'],1)
        self.assertEqual([i['id'] for i in queue['items']],[newer['id'],older['id']])
        self.assertNotIn('form',queue['items'][0]);self.assertNotIn('details',queue['items'][0]);self.assertNotIn('attachments',queue['items'][0])
        self.assertEqual(self.manager.workbench(task_id=older['task_id'])['total'],1)
        self.assertEqual(self.manager.workbench(source='不匹配')['total'],0)

    def test_cross_task_duplicate_is_rejected_even_after_two_confirmations(self):
        items=[self.confirm(self.item()) for _ in range(2)]
        with self.assertRaises(RuntimeError):self.manager.publish_batch(str(uuid.uuid4()),[{'id':i['id'],'revision':i['revision']} for i in items])
        self.assertEqual(self.db.catalog()['total'],627)

    def test_roll_back_when_second_create_fails(self):
        items=[self.confirm(self.item(stem)) for stem in ['题目一','题目二']];original=self.db.create_question;count=[0]
        def fail(*args):
            count[0]+=1
            if count[0]==2:raise ValueError('模拟第二题写入失败')
            return original(*args)
        with patch.object(self.db,'create_question',side_effect=fail):
            with self.assertRaises(ValueError):self.manager.publish_batch(str(uuid.uuid4()),[{'id':i['id'],'revision':i['revision']} for i in items])
        self.assertEqual(self.db.catalog()['total'],627);self.assertTrue(all(self.manager.get_item(i['id'])['review_stage']=='publish' for i in items))

    def test_discarded_core_draft_is_not_a_ghost_review_candidate(self):
        item=self.item()
        with self.db.transaction() as conn:
            conn.execute('INSERT INTO closed_drafts VALUES(?,?,NULL)',(item['draft_id'],item['draft_revision']))
            conn.execute('DELETE FROM drafts WHERE id=?',(item['draft_id'],))
        queue=self.manager.workbench();self.assertEqual(queue['counts']['review'],0);self.assertEqual(queue['counts']['skipped'],1)

    def test_figure_issue_targets_exact_page_and_deduplicates_generic_validation(self):
        from backend.agent_review import issues
        item=self.item();figure={'id':'fig2','image_id':self.image['id'],'rect':[.1,.2,.8,.7],'field':'solution_tex'}
        item['details'].update(figures=[figure],figures_confirmed=True,figure_issues=['配图 fig2 边缘接触文字或线条，请调整裁剪并确认完整性'],validation_error='配图边缘可能截断，请先调整标记配图的裁剪范围，再确认完整性')
        found=issues(item);self.assertEqual(len(found),1)
        self.assertEqual(found[0]['target']['figure_id'],'fig2');self.assertEqual(found[0]['target']['image_id'],self.image['id'])
        self.assertEqual(found[0]['action'],'crop_figure')

    def test_edge_warning_cannot_be_cleared_by_integrity_checkbox(self):
        item=self.item();details=item['details'];details.update(figures=[{'id':'fig2','image_id':self.image['id'],'rect':[.1,.2,.8,.7],'field':'solution_tex'}],figure_issues=['配图 fig2 边缘接触文字或线条'])
        self.manager._set_item(item['id'],'needs_review',details)
        item=self.manager.get_item(item['id']);changed=self.manager.update_item(item['id'],item['revision'],{'figures_confirmed':True})
        self.assertFalse(changed['details']['figures_confirmed']);self.assertTrue(changed['details']['figure_issues'])

    def test_failed_compilation_becomes_stale_after_external_draft_edit(self):
        item=self.item()
        with patch.object(self.manager,'compile_item',side_effect=ValueError('Undefined control sequence')):failed=self.manager.validate_item(item['id'])
        self.assertIn('Undefined',failed['details']['validation_error'])
        draft=self.db.get_draft(item['draft_id']);draft['content']['form']['question_tex']='修正后的题干'
        self.db.save_draft(item['draft_id'],draft['revision'],None,None,draft['content'])
        current=self.manager.get_item(item['id']);self.assertIsNone(current['details']['validation_error']);self.assertFalse(current['validation_current'])

    def test_successful_compilation_does_not_equal_human_review_and_edit_invalidates_it(self):
        item=self.item()
        with patch.object(self.manager,'compile_item'):item=self.manager.validate_item(item['id'])
        self.assertTrue(item['validation_current']);self.assertEqual(item['review_stage'],'review')
        changed=self.manager.update_item(item['id'],item['revision'],{'form':{'answer_tex':'人工答案'}})
        self.assertFalse(changed['validation_current']);self.assertIsNone(changed['reviewed_at'])

    def test_replacing_flagged_crop_preserves_original_page_and_can_confirm(self):
        item=self.item();item=self.manager.crop_figure(item['id'],item['revision'],{'image_id':self.image['id'],'rect':[.1,.2,.8,.7]},'solution_tex')
        fig=item['details']['figures'][0];details=item['details'];details['figure_issues']=['配图 '+fig['id']+' 边缘接触文字或线条']
        self.manager._set_item(item['id'],'needs_review',details);item=self.manager.get_item(item['id'])
        item=self.manager.crop_figure(item['id'],item['revision'],{'image_id':self.image['id'],'rect':[.05,.1,.95,.9]},'solution_tex',fig['id'])
        self.assertFalse(item['details']['figure_issues']);self.assertFalse(item['details']['figures_confirmed'])
        self.assertEqual(item['details']['figures'][0]['image_id'],self.image['id'])
        item=self.manager.update_item(item['id'],item['revision'],{'figures_confirmed':True})
        item=self.confirm(item);self.assertEqual(item['review_stage'],'publish')

    def test_compiler_pass_is_visible_even_while_answer_conflict_blocks_review(self):
        item=self.item();item=self.manager.update_item(item['id'],item['revision'],{'answer_conflict':True})
        with patch.object(self.manager,'compile_item'):item=self.manager.validate_item(item['id'])
        self.assertTrue(item['validation_current']);self.assertTrue(any(i['code']=='answer_conflict' for i in item['issues']))
        self.assertEqual(item['review_stage'],'review');self.assertIsNone(item['reviewed_at'])
