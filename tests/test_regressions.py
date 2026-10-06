import hashlib
import io
import json
import shutil
import sqlite3
import uuid
import threading
from pathlib import Path
from unittest.mock import patch

from tests.support import IsolatedCase, ROOT, payload, catalog, runtime, latex_service, papers


class SettingsTests(IsolatedCase):
    def test_corrupt_settings_can_be_saved(self):
        runtime.SETTINGS.write_text('{broken', encoding='utf-8')
        self.assertEqual(runtime.read_settings(), {})
        runtime.set_latex_path('')
        self.assertEqual(runtime.read_settings()['xelatex_path'], '')
        self.assertTrue(list(self.data.glob('settings.corrupt-*.json')))

    def test_wrong_shape_is_recovered(self):
        for value in [[], None, {'xelatex_path': []}]:
            runtime.SETTINGS.write_text(json.dumps(value), encoding='utf-8')
            self.assertIsInstance(runtime.read_settings(), dict)
            self.assertIsInstance(runtime.latex_status()['message'], str)

    def test_last_good_settings_survive_corruption(self):
        runtime.set_latex_path('')
        runtime.SETTINGS.write_text('', encoding='utf-8')
        self.assertEqual(runtime.read_settings()['xelatex_path'], '')
        self.assertTrue(runtime.latex_status().get('warning'))


class CatalogTests(IsolatedCase):
    def test_legacy_counts_assets_and_positions_survive_upgrade(self):
        counts = {item['code']:item['count'] for item in self.db.catalog()['collections']}
        self.assertEqual(counts, {'gaoyi-first':518,'gaoyi-second':0,'gaokao-first':0,'gaokao-second':0,'misc':109})
        self.assertEqual(self.db.point_count('6.1','misc'),62)
        self.assertEqual(self.db.point_count('bridge.1','misc'),47)
        with self.db.connect() as conn:
            self.assertEqual(conn.execute('pragma integrity_check').fetchone()[0],'ok')
            self.assertFalse(conn.execute('pragma foreign_key_check').fetchall())
            groups=conn.execute('select collection_code,point_code,count(*) as n,min(position) as first,max(position) as last from questions group by collection_code,point_code').fetchall()
            self.assertTrue(all(row['first']==1 and row['n']==row['last'] for row in groups))
        conn.close()

    def test_pool_limit_manual_random_and_undo_survive(self):
        questions=self.db.ordered_snapshot_all()
        for question in questions[:100]:self.db.pool_add(question['id'])
        with self.assertRaises(ValueError):self.db.pool_add(questions[100]['id'])
        ids=[questions[i]['id'] for i in [2,0,1]]
        snapshot,_=self.db.paper_snapshot('manual',ids)
        self.assertEqual([question['id'] for question in snapshot],[question['id'] for question in questions[:3]])
        snapshot,_=self.db.paper_snapshot('random',count=20)
        self.assertEqual(len({question['id'] for question in snapshot}),20)
        with self.assertRaises(ValueError):self.db.paper_snapshot('random',count=21)
        self.db.pool_remove(ids)
        reopened=catalog.CatalogDB(self.db.path)
        self.assertTrue(reopened.pool_state()['can_undo'])
        reopened.pool_undo()
        self.assertEqual([question['id'] for question in reopened.pool_items()][:3],[question['id'] for question in questions[:3]])
        reopened.delete_question(questions[0]['id'],questions[0]['revision'])
        self.assertNotIn(questions[0]['id'],{question['id'] for question in reopened.pool_items()})

    def test_future_schema_is_rejected_without_writes(self):
        with self.db.transaction() as conn:
            conn.execute("UPDATE metadata SET value='99' WHERE key='schema_version'")
        # Close/checkpoint before taking the physical hash.
        with sqlite3.connect(self.db.path) as conn:
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        conn.close()
        before = hashlib.sha256(self.db.path.read_bytes()).digest()
        with self.assertRaises(RuntimeError):
            self.db.initialize()
        self.assertEqual(before, hashlib.sha256(self.db.path.read_bytes()).digest())

    def test_migration_is_backed_up_and_idempotent(self):
        self.assertTrue(list((self.data/'backups').glob('*.sqlite3')))
        before = self.db.ordered_snapshot_all()
        backups = list((self.data/'backups').glob('*.sqlite3'))
        self.db.initialize()
        self.assertEqual(before, self.db.ordered_snapshot_all())
        self.assertEqual(backups, list((self.data/'backups').glob('*.sqlite3')))

    def test_old_content_draft_preserves_current_position(self):
        self.create()
        question = self.create(position=2)
        draft_id = str(uuid.uuid4())
        self.db.save_draft(draft_id, 0, question['id'], question['revision'], self.draft(question))
        self.create(position=1)
        result, _ = self.db.publish_draft(draft_id, 1, payload(position=2), False)
        self.assertEqual(result['question']['position'], 3)

    def test_manual_move_checks_order_version(self):
        question = self.create()
        draft_id = str(uuid.uuid4())
        version = self.db.point_order_revision('gaoyi-second', '6.1')
        self.db.save_draft(draft_id, 0, question['id'], question['revision'],
            self.draft(question), position_mode='move', target_order_revision=version)
        self.create(position=2)
        with self.assertRaises(catalog.PositionConflict):
            self.db.publish_draft(draft_id, 1, payload(), False)
        self.assertEqual(self.db.get_draft(draft_id)['revision'], 1)

    def test_content_update_does_not_change_order_version(self):
        question = self.create()
        version = self.db.point_order_revision('gaoyi-second', '6.1')
        self.db.update_question(question['id'], question['revision'], payload(answer_tex='二'))
        self.assertEqual(version, self.db.point_order_revision('gaoyi-second', '6.1'))


class ExportTests(IsolatedCase):
    def test_legacy_export_manifest_is_still_readable(self):
        self.create()
        manager=latex_service.ExportManager(self.db)
        with patch.object(latex_service,'compile_tex',return_value=b'%PDF'):
            manager._run_export('gaoyi-second')
        folder=latex_service.active_export_dir('gaoyi-second')
        manifest=json.loads((folder/'export_manifest.json').read_text('utf-8'))
        manifest['format_version']=2
        manifest.pop('assets');manifest.pop('template_sha256')
        for item in manifest['questions']:item.pop('content_sha256')
        (folder/'export_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
        (folder/'preamble.tex').unlink()
        reopened=latex_service.ExportManager(self.db)
        self.assertTrue(reopened.status('gaoyi-second')['available'])
        self.assertEqual(reopened.status('gaoyi-second')['state'],'ready')

    def test_snapshot_and_concurrent_delete_are_serialized(self):
        name=str(uuid.uuid4())+'.png';image=next((self.data/'assets').glob('*.png')).read_bytes()
        (self.data/'assets'/name).write_bytes(image)
        question=self.create(question_tex=r'\includegraphics{assets/'+name+'}')
        entered=threading.Event();release=threading.Event();delete_started=threading.Event();deleted=threading.Event()
        captured=[];failures=[]
        original=catalog.asset_path
        def held_path(*args,**kwargs):
            result=original(*args,**kwargs)
            if threading.current_thread().name=='snapshot-test':
                entered.set()
                if not release.wait(3):raise TimeoutError('snapshot test release')
            return result
        def snapshot():
            try:captured.append(self.db.collection_snapshot('gaoyi-second'))
            except Exception as error:failures.append(error)
        def delete():
            delete_started.set()
            try:
                _,removed=self.db.delete_question(question['id'],question['revision'])
                self.db.cleanup_assets(removed)
                deleted.set()
            except Exception as error:failures.append(error)
        with patch.object(catalog,'asset_path',side_effect=held_path):
            reader=threading.Thread(target=snapshot,name='snapshot-test');reader.start()
            self.assertTrue(entered.wait(2))
            writer=threading.Thread(target=delete);writer.start()
            self.assertTrue(delete_started.wait(1))
            try:self.assertFalse(deleted.wait(.05),'delete passed active resource capture')
            finally:release.set();reader.join(3);writer.join(3)
        self.assertFalse(failures)
        self.assertFalse(reader.is_alive() or writer.is_alive())
        self.assertEqual(captured[0][2]['assets/'+name],image)
        self.assertTrue(deleted.is_set())

    def test_collection_export_freezes_assets_before_delete(self):
        name = str(uuid.uuid4())+'.png'
        image = next((self.data/'assets').glob('*.png')).read_bytes()
        (self.data/'assets'/name).write_bytes(image)
        question = self.create(question_tex=r'图：\includegraphics{assets/'+name+'}')
        calls = []
        def compile_frozen(source, *args, **kwargs):
            resource_root = kwargs['resource_root']
            if not calls:
                _, removed = self.db.delete_question(question['id'], question['revision'])
                self.db.cleanup_assets(removed)
            calls.append(source)
            self.assertEqual((resource_root/'assets'/name).read_bytes(), image)
            self.assertTrue((resource_root/'preamble.tex').is_file())
            return b'%PDF-1.4\n%%EOF'
        manager = latex_service.ExportManager(self.db)
        with patch.object(latex_service, 'compile_tex', side_effect=compile_frozen):
            manager._run_export('gaoyi-second')
        status = manager.status('gaoyi-second')
        self.assertTrue(status['available'])
        self.assertTrue(status['stale'])  # The frozen export succeeded, but the live bank changed.
        self.assertNotEqual(status['state'], 'failed')
        folder = latex_service.active_export_dir('gaoyi-second')
        self.assertTrue((folder/'assets'/name).is_file())
        self.assertNotIn(str(self.data).replace('\\', '/'), (folder/'questions.tex').read_text('utf-8'))

    def test_training_archive_keeps_template_and_images(self):
        question = next(q for q in self.db.ordered_snapshot_all() if r'\includegraphics' in q['question_tex'])
        self.db.pool_add(question['id'])
        snapshot, assets = self.db.paper_snapshot('manual', [question['id']])
        manager = papers.PaperManager(self.db)
        with patch.object(papers, 'compile_tex', return_value=b'%PDF-1.4\n%%EOF'):
            manager._run('manual', snapshot, assets)
        folder = papers.active_paper_dir()
        self.assertTrue((folder/'preamble.tex').is_file())
        self.assertTrue(all((folder/name).is_file() for name in assets))
        self.assertIn(r'\graphicspath{{./}}', (folder/'questions.tex').read_text('utf-8'))


class AssetTests(IsolatedCase):
    def test_fake_png_is_rejected(self):
        from backend.assets import validate_upload
        with self.assertRaises(ValueError):
            validate_upload(b'not a PNG', '.png')

    def test_valid_png_is_accepted(self):
        from backend.assets import validate_upload
        validate_upload(next((self.data/'assets').glob('*.png')).read_bytes(), '.png')
