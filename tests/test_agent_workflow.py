import asyncio
import io
import json
import threading
import time
import uuid
from unittest.mock import patch
from tests.support import IsolatedCase,catalog,latex_service
from backend.agent import AgentManager
from backend.deepseek import DeepSeekProvider,ProviderError


class WorkflowTests(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.manager=AgentManager(self.db)
        self.session=self.manager.create_session()
        from PIL import Image
        buffer=io.BytesIO();Image.new('RGB',(100,100),'white').save(buffer,format='PNG')
        self.image=self.manager.attach(self.session['id'],'测试.png',buffer.getvalue())
        self.addCleanup(self.manager.stop)

    def candidate(self,**changes):
        return {'type':'fill','question_tex':'计算 $1+1$。','options':[],'answer_tex':'','solution_tex':'',
                'collection_code':'gaoyi-first','point_code':'2.1','classification_reason':'计算练习','original_number':'1',
                'regions':[{'image_id':self.image['id'],'rect':[0,0,1,1]}],**changes}

    def task(self):return self.manager.create_task(self.session['id'],{'attachment_ids':[self.image['id']]})

    def wait(self,tid):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            task=self.manager.get_task(tid)
            if task['state'] not in {'pending','recognizing','processing','chatting'}:return task
            time.sleep(.02)
        self.fail('agent worker timeout')

    def test_remote_two_question_pipeline_saves_drafts_generates_and_validates(self):
        class FakeProvider:
            prices={'input':2,'cached_input':.04,'output':8}
            def status(self):return {'configured':True,'prices':self.prices}
            def configure(self,*args):pass
            async def json(provider,messages,**options):
                callback=options.get('usage_callback');callback(None);callback({'prompt_tokens':100,'completion_tokens':20,'total_tokens':120})
                if '只建立' in messages[0]['content']:
                    return {'segments':[{'number':'1','role':'question','regions':[{'image_id':'view-1','rect':[0,0,1,.5]}]},
                        {'number':'2','role':'question','regions':[{'image_id':'view-1','rect':[0,.5,1,1]}]}]},'mock-model'
                if '只提取' in messages[0]['content']:
                    number=json.loads(messages[1]['content'][0]['text'])['original_number']
                    return {'questions':[self.candidate(question_tex='$1+1$' if number=='1' else '$2+2$',original_number=number,regions=[{'image_id':'view-1','rect':[0,0,1,1]}])]},'mock-model'
                if 'schema=' in messages[0]['content']:
                    return {'questions':[self.candidate(regions=[{'image_id':'view-1','rect':[0,0,1,.5]}]),self.candidate(question_tex='$2+2=$？',regions=[{'image_id':'view-1','rect':[0,.5,1,1]}])]},'mock-model'
                return {'answer_tex':'2','solution_tex':'由加法得 $1+1=2$。','uncertainties':[],'answer_conflict':False},'mock-model'
        self.manager.provider=FakeProvider()
        with patch.object(self.manager,'compile_item',return_value=None):
            self.manager.start();task=self.manager.start_import(self.session['id'],[self.image['id']],'提取',request_id=str(uuid.uuid4()))
            finished=self.wait(task['id'])
        self.assertEqual(finished['state'],'review');self.assertEqual(len(finished['items']),2)
        self.assertTrue(all(item['state']=='ready' for item in finished['items']))
        self.assertTrue(all(item['details']['answer_origin']=='ai' and item['details']['solution_origin']=='ai' for item in finished['items']))
        self.assertEqual(finished['calls'],5);self.assertEqual(finished['usage']['prompt_tokens'],500)
        self.assertEqual(self.db.catalog()['total'],627)

    def test_figures_are_materialized_and_original_answer_is_preserved(self):
        task=self.task()
        iid=self.manager.accept_candidates(task['id'],[self.candidate(question_tex='图：[FIGURE:f1]',answer_tex='A',solution_tex='原解析',answer_origin='original',solution_origin='original',figures=[{'id':'f1','field':'question_tex','image_id':self.image['id'],'rect':[0,0,.5,.5]}])])[0]
        item=self.manager.get_item(iid)
        self.assertIn(r'\includegraphics',item['form']['question_tex'])
        self.assertTrue((catalog.DATA_DIR/item['details']['allowed_assets'][0]).is_file())
        async def solve(*args,**kwargs):return {'answer_tex':'B','solution_tex':'AI 解析','answer_conflict':True,'uncertainties':[]},'mock'
        with patch.object(self.manager.provider,'json',side_effect=solve),patch.object(self.manager,'compile_item',return_value=None):
            asyncio.run(self.manager._process_item(iid,threading.Event(),force_solve=True))
        item=self.manager.get_item(iid)
        self.assertEqual(item['form']['answer_tex'],'A');self.assertEqual(item['form']['solution_tex'],'原解析')
        self.assertTrue(item['details']['answer_conflict']);self.assertEqual(item['state'],'needs_review')

    def test_manual_crop_split_merge_preserve_originals_and_limit(self):
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate()])[0]
        item=self.manager.get_item(iid)
        split=self.manager.restructure(task['id'],[{'id':iid,'revision':item['revision']}],[[{'image_id':self.image['id'],'rect':[0,0,1,.5]}],[{'image_id':self.image['id'],'rect':[0,.5,1,1]}]])
        self.assertEqual(split['items'][0]['state'],'skipped')
        self.assertEqual(len(self.db.list_drafts()),3)
        children=split['items'][1:]
        merged=self.manager.restructure(task['id'],[{'id':x['id'],'revision':x['revision']} for x in children],[children[0]['details']['regions']+children[1]['details']['regions']])
        self.assertEqual(len([x for x in merged['items'] if x['state']!='skipped']),1)
        self.assertTrue(self.manager.attachment_file(self.image['id']).is_file())

    def test_publish_rolls_back_every_question_if_last_item_fails(self):
        task=self.task();ids=self.manager.accept_candidates(task['id'],[self.candidate(answer_tex='2',solution_tex='解析'),self.candidate(question_tex='$3+3$',answer_tex='6',solution_tex='解析')])
        with patch.object(self.manager,'compile_item',return_value=None):
            for iid in ids:
                current=self.manager.get_item(iid);self.manager.confirm_review(iid,current['revision'],str(uuid.uuid4()))
        items=self.manager.get_task(task['id'])['items'];selection=[{'id':x['id'],'revision':x['revision']} for x in items]
        original=self.db.create_question;calls=[]
        def fail(form,conn=None):
            calls.append(form)
            if len(calls)==2:raise ValueError('injected failure')
            return original(form,conn)
        with patch.object(self.db,'create_question',side_effect=fail):
            with self.assertRaises(ValueError):self.manager.publish(task['id'],str(uuid.uuid4()),selection)
        self.assertEqual(self.db.catalog()['total'],627);self.assertEqual(len(self.db.list_drafts()),2)

    def test_external_draft_edit_invalidates_ready_and_blocks_replacement(self):
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate(answer_tex='2',solution_tex='解析')])[0]
        with patch.object(self.manager,'compile_item',return_value=None):self.manager.validate_item(iid)
        item=self.manager.get_item(iid);draft=self.db.get_draft(item['draft_id'])
        draft['content']['form']['question_tex']='人工修改'
        self.db.save_draft(draft['id'],draft['revision'],None,None,draft['content'])
        self.assertEqual(self.manager.get_item(iid)['state'],'needs_review')
        with self.assertRaises(RuntimeError):self.manager._replace_item(iid,item['revision'],self.candidate(),item['draft_revision'])

    def test_duplicates_require_explicit_keep_and_recheck(self):
        question=self.create(question_tex='同一题目内容测试',answer_tex='2',solution_tex='解析')
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate(question_tex=question['question_tex'],answer_tex='2',solution_tex='解析')])[0]
        with patch.object(self.manager,'compile_item',return_value=None):item=self.manager.validate_item(iid)
        self.assertEqual(item['state'],'needs_review');self.assertTrue(item['details']['duplicates'])
        item=self.manager.update_item(iid,item['revision'],{'allow_duplicate':True})
        with patch.object(self.manager,'compile_item',return_value=None):item=self.manager.validate_item(iid)
        self.assertEqual(item['state'],'ready')

    def test_resume_recognition_reuses_saved_checkpoint(self):
        task=self.task();block={'alias':'view-1','data':'AA=='}
        blocks=[{**block,'alias':'view-'+str(i+1)} for i in range(7)]
        mapping={b['alias']:{'image_id':self.image['id'],'rect':[0,0,1,1]} for b in blocks}
        count=[]
        async def recognize(messages,**options):
            count.append(messages)
            if len(count)==2:raise ProviderError('模拟网络中断')
            alias='view-1' if len(count)==1 else 'view-7'
            return {'questions':[self.candidate(question_tex='$1+1$' if len(count)==1 else '$2+2$',original_number='1' if len(count)==1 else '2',regions=[{'image_id':alias,'rect':[0,0,1,1]}])]},'mock'
        with patch.object(self.manager,'_visual_blocks',return_value=(blocks,mapping)),patch.object(self.manager.provider,'json',side_effect=recognize):
            with self.assertRaises(ProviderError):asyncio.run(self.manager._recognize(task['id'],threading.Event()))
            partial=self.manager.get_task(task['id']);self.assertEqual(len(partial['items']),1)
            self.assertEqual(partial['payload']['recognition_checkpoint']['next_index'],6)
            asyncio.run(self.manager._recognize(task['id'],threading.Event()))
        self.assertEqual(len(count),3);self.assertEqual(len(self.manager.get_task(task['id'])['items']),2)

    def test_startup_marks_active_tasks_paused_and_retains_drafts(self):
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate()])[0]
        self.manager.store.task_update(task['id'],state='processing')
        self.manager.start()
        self.assertEqual(self.manager.get_task(task['id'])['state'],'paused')
        self.assertEqual(len(self.db.list_drafts()),1)

    def test_edit_shape_and_tool_cross_task_access_are_rejected(self):
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate()])[0]
        item=self.manager.get_item(iid)
        with self.assertRaises(ValueError):self.manager.update_item(iid,item['revision'],{'form':{'options':'ABCD'}})
        other=self.task();otherid=self.manager.accept_candidates(other['id'],[self.candidate()])[0]
        original=self.manager.get_item(otherid)
        responses=[]
        async def remote(messages,**kwargs):
            responses.append(messages.copy())
            if len(responses)==1:return {'content':None,'tool_calls':[{'id':'attempt','function':{'name':'update_candidate','arguments':json.dumps({'item_id':otherid,'revision':original['revision'],'changes':{'form':{'question_tex':'不应覆盖'}}})}}]},'mock'
            return {'content':'处理结束'},'mock'
        with patch.object(self.manager.provider,'request',side_effect=remote):
            asyncio.run(self.manager._chat_turn(task['id'],{'text':'修改','request_id':str(uuid.uuid4())},threading.Event()))
        self.assertFalse(json.loads(responses[1][-1]['content'])['ok'])
        self.assertEqual(self.manager.get_item(otherid)['form'],original['form'])
        self.assertEqual(self.db.catalog()['total'],627)

    def test_clearing_credentials_cancels_active_request(self):
        self.manager.provider.configure('test-key')
        signal=threading.Event();self.manager._cancel['test']=signal
        self.manager.configure('')
        self.assertTrue(signal.is_set());self.assertFalse(self.manager.config_status()['configured'])

    def test_at_most_two_remote_item_requests_run_concurrently(self):
        task=self.task();ids=self.manager.accept_candidates(task['id'],[self.candidate(question_tex=f'不同题目{i}') for i in range(5)])
        counts={'active':0,'maximum':0}
        async def remote(messages,**kwargs):
            counts['active']+=1;counts['maximum']=max(counts['maximum'],counts['active'])
            await asyncio.sleep(.04);counts['active']-=1
            return {'answer_tex':'2','solution_tex':'解析','uncertainties':[],'answer_conflict':False},'mock'
        with patch.object(self.manager.provider,'json',side_effect=remote),patch.object(self.manager,'compile_item',return_value=None):
            asyncio.run(self.manager._run(task['id'],'process',{'item_ids':ids},threading.Event()))
        self.assertEqual(counts['maximum'],2)

    def test_same_import_nonce_replays_without_another_job_and_rejects_changed_input(self):
        self.manager.provider.configure('test-key');rid=str(uuid.uuid4())
        with patch.object(self.manager,'_schedule') as schedule:
            first=self.manager.start_import(self.session['id'],[self.image['id']],'提取',request_id=rid)
            second=self.manager.start_import(self.session['id'],[self.image['id']],'提取',request_id=rid)
            self.assertEqual(first['id'],second['id']);self.assertEqual(schedule.call_count,1)
            with self.assertRaises(RuntimeError):self.manager.start_import(self.session['id'],[self.image['id']],'不同要求',request_id=rid)

    def test_interrupted_chat_can_resume_but_completed_chat_does_not_repeat_tools(self):
        task=self.task();rid=str(uuid.uuid4());self.manager.provider.configure('test-key')
        self.manager.store.message(self.session['id'],'user','修正',rid)
        with patch.object(self.manager,'_schedule') as schedule:
            self.manager.chat(task['id'],'修正',rid)
            self.assertEqual(schedule.call_count,1)
            self.manager.store.message(self.session['id'],'assistant','修正已完成',rid)
            self.manager.chat(task['id'],'修正',rid)
            self.assertEqual(schedule.call_count,1)
            with self.assertRaises(RuntimeError):self.manager.chat(task['id'],'不同指令',rid)

    def test_new_formal_duplicate_after_validation_blocks_publish(self):
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate(question_tex='同一题干的重复检查',answer_tex='2',solution_tex='解析')])[0]
        with patch.object(self.manager,'compile_item',return_value=None):item=self.manager.validate_item(iid)
        self.create(question_tex=item['form']['question_tex'],answer_tex='2',solution_tex='解析')
        with self.assertRaises(RuntimeError):self.manager.publish(task['id'],str(uuid.uuid4()),[{'id':iid,'revision':item['revision']}])
        self.assertEqual(self.db.catalog()['total'],628)

    def test_preimport_crop_is_mapped_back_and_cannot_omit_selected_images(self):
        task=self.manager.create_task(self.session['id'],{'attachment_ids':[self.image['id']],
            'input_regions':[{'image_id':self.image['id'],'rect':[.2,.3,.8,.9]}]})
        blocks,mapping=self.manager._visual_blocks(task)
        self.assertEqual(len(blocks),1)
        region=self.manager._map_region({'image_id':'view-1','rect':[0,0,1,1]},mapping)
        self.assertEqual(region['image_id'],self.image['id'])
        for got,wanted in zip(region['rect'],[.2,.3,.8,.9]):self.assertAlmostEqual(got,wanted)
        with self.assertRaises(ValueError):self.manager.create_task(self.session['id'],{'attachment_ids':[self.image['id']],'input_regions':[]})

    def test_chat_can_merge_candidates_and_reprocess_without_formal_write(self):
        task=self.task();ids=self.manager.accept_candidates(task['id'],[self.candidate(question_tex='第一个小问'),self.candidate(question_tex='第二个小问')])
        original=[self.manager.get_item(iid) for iid in ids];turns=[]
        async def tools(messages,**kwargs):
            turns.append(messages)
            if len(turns)==1:
                action={'items':[{'id':i['id'],'revision':i['revision']} for i in original],
                        'groups':[[region for item in original for region in item['details']['regions']]]}
                return {'content':None,'tool_calls':[{'id':'merge','function':{'name':'restructure_candidates','arguments':json.dumps(action)}}]},'mock'
            return {'content':'已合并候选题，尚未入库'},'mock'
        async def generate(messages,**kwargs):
            if 'schema=' in messages[0]['content']:return {'questions':[self.candidate(question_tex='合并后的综合练习',regions=[{'image_id':'view-1','rect':[0,0,1,1]}])]},'mock'
            return {'answer_tex':'2','solution_tex':'解析','answer_conflict':False,'uncertainties':[]},'mock'
        with patch.object(self.manager.provider,'request',side_effect=tools),patch.object(self.manager.provider,'json',side_effect=generate),patch.object(self.manager,'compile_item',return_value=None):
            asyncio.run(self.manager._chat_turn(task['id'],{'text':'合并前两题','request_id':str(uuid.uuid4())},threading.Event()))
        items=self.manager.get_task(task['id'])['items']
        self.assertEqual([i['state'] for i in items],['skipped','skipped','ready'])
        self.assertEqual(self.db.catalog()['total'],627)

    def test_missing_latex_does_not_spend_requests_on_format_repairs(self):
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate()])[0]
        async def solve(*args,**kwargs):return {'answer_tex':'2','solution_tex':'解析','uncertainties':[],'answer_conflict':False},'mock'
        with patch.object(self.manager.provider,'json',side_effect=solve) as remote,patch.object(self.manager,'compile_item',side_effect=latex_service.LatexError('未找到 XeLaTeX，请在设置中选择 xelatex.exe。')):
            asyncio.run(self.manager._process_item(iid,threading.Event()))
        self.assertEqual(remote.call_count,1)
        self.assertEqual(self.manager.get_item(iid)['state'],'needs_review')

    def test_unsafe_fragment_is_saved_as_unpublished_draft_and_never_compiled(self):
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate(question_tex=r'\input{settings.json}',answer_tex='2',solution_tex='解析')])[0]
        with patch.object(self.manager,'compile_item') as compile_item:
            item=self.manager.validate_item(iid)
        compile_item.assert_not_called();self.assertEqual(item['state'],'needs_review')
        self.assertEqual(self.db.get_draft(item['draft_id'])['content']['form']['question_tex'],r'\input{settings.json}')
        self.assertEqual(self.db.catalog()['total'],627)

    def test_transparent_png_is_flattened_on_white_for_vision(self):
        from PIL import Image
        buffer=io.BytesIO();Image.new('RGBA',(10,10),(0,0,0,0)).save(buffer,format='PNG')
        image=self.manager.attach(self.session['id'],'透明.png',buffer.getvalue())
        cropped=self.manager._crop({'image_id':image['id'],'rect':[0,0,1,1]})
        self.assertEqual(cropped.getpixel((0,0)),(255,255,255))

    def test_percent_format_is_repaired_without_losing_ai_origin(self):
        task=self.task();iid=self.manager.accept_candidates(task['id'],[self.candidate(question_tex='增长率为20%。')])[0]
        calls=[]
        async def remote(messages,**kwargs):
            calls.append(messages)
            if len(calls)==1:return {'answer_tex':'20%','solution_tex':'对应比例为0.2','uncertainties':[],'answer_conflict':False},'mock'
            return {'question_tex':r'增长率为20\%。','options':[],'answer_tex':r'$20\%$','solution_tex':'对应比例为0.2'},'mock'
        with patch.object(self.manager.provider,'json',side_effect=remote),patch.object(self.manager,'compile_item',return_value=None):
            asyncio.run(self.manager._process_item(iid,threading.Event()))
        item=self.manager.get_item(iid)
        self.assertEqual(item['state'],'ready',item['details'])
        self.assertEqual(item['details']['answer_origin'],'ai')
        self.assertEqual(item['details']['format_repair_count'],1)
        self.assertEqual(len(calls),2)
