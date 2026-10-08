import json
import shutil
import sqlite3
from contextlib import closing
import uuid
from unittest.mock import patch
from tests.support import IsolatedCase, payload
from backend.agent import AgentManager
from backend.bank_exports import BankExports
from backend import latex_service


class BankTests(IsolatedCase):
    def test_empty_ai_session_does_not_block_deleting_an_empty_bank(self):
        bank=self.db.create_bank('临时题库')['id'];manager=AgentManager(self.db)
        manager.create_session(bank_id=bank)
        self.assertTrue(self.db.delete_bank(bank)['deleted'])

    def test_migration_failure_rolls_back_bank_rebuild(self):
        from tests.support import ROOT
        from backend import banks
        from backend.catalog import CatalogDB
        path=self.data/'rollback-bank.sqlite3'
        shutil.copy2(ROOT/'resources/seed/question_bank.sqlite3',path)
        original=banks.migrate
        def fail(conn,stamp):
            original(conn,stamp)
            raise RuntimeError('injected migration failure')
        with patch.object(banks,'migrate',side_effect=fail):
            with self.assertRaises(RuntimeError):CatalogDB(path).initialize()
        with closing(sqlite3.connect(path)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM questions').fetchone()[0],627)
            self.assertFalse(conn.execute("SELECT 1 FROM sqlite_master WHERE name='banks'").fetchone())
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertTrue(list((self.data/'backups').glob('*schema-0-*.sqlite3')))

    def test_ai_candidate_publish_remains_in_session_bank(self):
        from tests.test_agent import AgentContractTests
        bank=self.db.create_bank('自主练习')['id'];manager=AgentManager(self.db)
        session=manager.create_session(bank_id=bank)
        image=AgentContractTests.attachment(self,manager,session)
        task=manager.create_task(session['id'],{'attachment_ids':[image['id']]})
        candidate=AgentContractTests.candidate(self,image)
        iid=manager.accept_candidates(task['id'],[candidate])[0]
        self.assertEqual(manager.get_item(iid)['form']['bank_id'],bank)
        self.assertEqual(manager.workbench()['total'],0)
        with patch.object(manager,'compile_item',return_value=None):
            item=manager.get_item(iid);item=manager.confirm_review(iid,item['revision'],str(uuid.uuid4()))
        result=manager.publish_batch(str(uuid.uuid4()),[{'id':iid,'revision':item['revision']}])
        self.assertEqual(self.db.get_question(result['items'][0]['question_id'])['bank_id'],bank)
        self.assertEqual(self.db.catalog()['total'],627)
        self.assertEqual(self.db.catalog(bank)['total'],1)

    def test_new_bank_empty_and_independent_positions(self):
        bank=self.db.create_bank('课内练习')['id']
        self.assertEqual(self.db.catalog()['bank_name'],'系统题库')
        self.assertEqual(self.db.catalog(bank)['total'],0)
        self.assertEqual(len(self.db.catalog(bank)['collections']),5)
        _,q=self.db.create_question(payload(bank_id=bank))
        self.assertEqual(q['position'],1)
        self.assertEqual(self.db.catalog(bank)['total'],1)
        self.assertEqual(self.db.catalog()['total'],627)
        with self.assertRaises(ValueError):self.db.create_bank('课内练习')
        with self.assertRaises(ValueError):self.db.delete_bank(bank)
        with self.assertRaises(ValueError):self.db.delete_bank('system')

    def test_copy_move_idempotency_and_draft_conflict(self):
        bank=self.db.create_bank('课外补充')['id'];q=self.create()
        selection=[{'id':q['id'],'revision':q['revision']}];request=str(uuid.uuid4())
        copied=self.db.transfer_questions(selection,bank,'copy',request_id=request)
        self.assertEqual(copied,self.db.transfer_questions(selection,bank,'copy',request_id=request))
        self.assertNotEqual(copied['items'][0]['id'],q['id'])
        self.db.pool_add(q['id'])
        moved=self.db.transfer_questions(selection,bank,'move')
        self.assertEqual(moved['items'][0]['id'],q['id'])
        self.assertEqual(self.db.get_question(q['id'])['bank_id'],bank)
        self.assertEqual(self.db.pool_state()['count'],0)
        self.assertEqual([q['position'] for q in self.db.ordered_snapshot_all(bank)],[1,2])
        other=self.create();self.db.save_draft(str(uuid.uuid4()),0,other['id'],other['revision'],self.draft(other))
        with self.assertRaises(RuntimeError):self.db.transfer_questions([{'id':other['id'],'revision':other['revision']}],bank,'move')

    def test_pool_search_draft_and_ai_session_isolation(self):
        bank=self.db.create_bank('课外补充')['id'];_,q=self.db.create_question(payload(bank_id=bank,question_tex='独立题库题目'))
        self.db.pool_add(q['id'],bank)
        self.assertEqual(self.db.pool_state(bank)['count'],1)
        self.assertEqual(self.db.pool_state()['count'],0)
        with self.assertRaises(KeyError):self.db.pool_add(q['id'])
        self.assertEqual(self.db.search('独立题库题目'),[])
        self.assertEqual(len(self.db.search('独立题库题目',bank_id=bank)),1)
        self.assertEqual(len(self.db.search('独立题库题目',bank_id=None)),1)
        draft=self.db.save_draft(str(uuid.uuid4()),0,None,None,{'form':payload(bank_id=bank),'source_rows':[]})
        self.assertEqual(draft['bank_id'],bank)
        self.assertFalse(self.db.list_drafts())
        self.assertEqual(len(self.db.list_drafts(bank)),1)
        manager=AgentManager(self.db)
        session=manager.create_session(bank_id=bank)
        self.assertEqual(manager.sessions(),[])
        self.assertEqual(manager.sessions(bank)[0]['id'],session['id'])
        self.assertEqual(manager.workbench(bank_id=bank)['total'],0)

    def test_scope_export_and_cross_bank_rejection(self):
        bank=self.db.create_bank('课外补充')['id'];_,q=self.db.create_question(payload(bank_id=bank))
        exports=BankExports(self.db)
        scope={'kind':'selected','question_ids':[q['id']]}
        with patch.object(latex_service,'compile_tex',return_value=b'%PDF-test'):
            status=exports.schedule(bank,'gaoyi-second',scope)
            for thread in exports.threads:thread.join(timeout=5)
        self.assertEqual(exports.status(bank,'gaoyi-second',scope)['state'],'ready')
        folder=exports.folder(status['key'])
        manifest=json.loads((folder/'export_manifest.json').read_text('utf-8'))
        self.assertEqual(manifest['count'],1)
        self.assertEqual(manifest['bank_id'],bank)
        self.assertIn('课外补充',manifest['files']['question'])
        with self.assertRaises(ValueError):exports.specification('system','gaoyi-second',scope)
        self.db.rename_bank(bank,'独立练习')
        self.assertTrue(exports.status(bank,'gaoyi-second',scope)['stale'])
