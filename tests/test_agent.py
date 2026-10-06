import io
import json
import threading
import uuid
from unittest.mock import patch
from tests.support import IsolatedCase, payload, catalog, latex_service


class AgentContractTests(IsolatedCase):
    def manager(self):
        from backend.agent import AgentManager
        return AgentManager(self.db)

    def attachment(self, manager, session):
        from PIL import Image
        image=io.BytesIO();Image.new('RGB',(60,80),'white').save(image,format='PNG')
        return manager.attach(session['id'],'题目.png',image.getvalue())

    def candidate(self, attachment, **changes):
        return {'type':'fill','question_tex':r'计算 $1+1$。','options':[], 'answer_tex':'2',
            'solution_tex':r'$1+1=2$。','collection_code':'gaoyi-second','point_code':'6.1',
            'classification_reason':'向量题示例','classification_candidates':[], 'uncertainties':[],
            'answer_origin':'original','solution_origin':'original','original_number':'1',
            'regions':[{'image_id':attachment['id'],'rect':[0,0,1,1]}], 'figures':[], **changes}

    def test_agent_requires_configuration_without_touching_formal_bank(self):
        manager=self.manager();session=manager.create_session()
        self.assertFalse(manager.config_status()['configured'])
        image=self.attachment(manager,session)
        with self.assertRaises(RuntimeError):manager.start_import(session['id'],[image['id']],'提取')
        self.assertEqual(self.db.catalog()['total'],627)

    def test_multiple_candidates_become_drafts_and_atomic_publish_is_idempotent(self):
        manager=self.manager();session=manager.create_session();image=self.attachment(manager,session)
        task=manager.create_task(session['id'],{'attachment_ids':[image['id']],'instruction':'提取','source_title':'测试卷'})
        ids=manager.accept_candidates(task['id'],[self.candidate(image),self.candidate(image,question_tex='$2+2$',answer_tex='4',solution_tex='$2+2=4$')])
        self.assertEqual(len(ids),2);self.assertEqual(self.db.catalog()['total'],627)
        with patch.object(manager,'compile_item',return_value=None):
            for item_id in ids:
                current=manager.get_item(item_id);manager.confirm_review(item_id,current['revision'],str(uuid.uuid4()))
        items=manager.get_task(task['id'])['items'];request_id=str(uuid.uuid4())
        selection=[{'id':item['id'],'revision':item['revision']} for item in items]
        result=manager.publish(task['id'],request_id,selection)
        self.assertEqual(result,manager.publish(task['id'],request_id,selection))
        self.assertEqual(self.db.catalog()['total'],629)
        self.assertTrue(all(not self.db.get_question(item['question_id'])['verified'] for item in result['items']))
        self.assertEqual([q['position'] for q in self.db.ordered_snapshot('gaoyi-second')[1]],[1,2])

    def test_unknown_point_and_unreadable_text_cannot_publish(self):
        manager=self.manager();session=manager.create_session();image=self.attachment(manager,session)
        task=manager.create_task(session['id'],{'attachment_ids':[image['id']]})
        ids=manager.accept_candidates(task['id'],[self.candidate(image,point_code='invented',uncertainties=['下标不清楚'])])
        with patch.object(manager,'compile_item',return_value=None):manager.validate_item(ids[0])
        item=manager.get_task(task['id'])['items'][0]
        self.assertEqual(item['state'],'needs_review')
        with self.assertRaises(RuntimeError):manager.publish(task['id'],str(uuid.uuid4()),[{'id':item['id'],'revision':item['revision']}])

    def test_latex_file_access_and_obfuscated_commands_are_rejected(self):
        from backend.agent_tex import validate_agent_tex
        for tex in [r'\input{settings.json}',r'\csname input\endcsname{x}',r'\write18{cmd}',r'^^5cinput{x}',r'\begin{filecontents}{x}x\end{filecontents}']:
            with self.assertRaises(ValueError):validate_agent_tex(payload(question_tex=tex),set())
        validate_agent_tex(payload(question_tex=r'若 $x\in\mathbb{R}$，则 $\frac{x+1}{2}\ge 0$。'),set())

    def test_model_cannot_reference_other_sessions_images(self):
        manager=self.manager();session=manager.create_session();image=self.attachment(manager,session)
        other=manager.create_session();other_image=self.attachment(manager,other)
        task=manager.create_task(session['id'],{'attachment_ids':[image['id']]})
        with self.assertRaises(ValueError):manager.accept_candidates(task['id'],[self.candidate(other_image)])

    def test_user_edit_invalidates_validation_and_rejects_stale_version(self):
        manager=self.manager();session=manager.create_session();image=self.attachment(manager,session)
        task=manager.create_task(session['id'],{'attachment_ids':[image['id']]})
        item_id=manager.accept_candidates(task['id'],[self.candidate(image)])[0]
        with patch.object(manager,'compile_item',return_value=None):manager.validate_item(item_id)
        item=manager.get_item(item_id)
        manager.update_item(item_id,item['revision'],{'form':{**item['form'],'answer_tex':'3'}})
        with self.assertRaises(RuntimeError):manager.update_item(item_id,item['revision'],{'form':item['form']})
        self.assertNotEqual(manager.get_item(item_id)['state'],'ready')

    def test_image_count_and_format_limits(self):
        manager=self.manager();session=manager.create_session()
        images=[self.attachment(manager,session) for _ in range(21)]
        with self.assertRaises(ValueError):manager.create_task(session['id'],{'attachment_ids':[image['id'] for image in images]})
        with self.assertRaises(ValueError):manager.attach(session['id'],'fake.png',b'not PNG')
