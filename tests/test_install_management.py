import hashlib,sqlite3,tempfile,unittest
from pathlib import Path
from scripts.install_inventory import consistent_copy,database_inventory,tree_inventory


class InstallManagementTests(unittest.TestCase):
    def test_wal_backup_contains_committed_data_and_does_not_change_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.sqlite3';destination=root/'backup.sqlite3'
            conn=sqlite3.connect(source);conn.execute('PRAGMA journal_mode=WAL');conn.execute('CREATE TABLE metadata(key TEXT,value TEXT)');conn.execute("INSERT INTO metadata VALUES('schema_version','8')");conn.execute('CREATE TABLE drafts(id TEXT,content TEXT)');conn.execute("INSERT INTO drafts VALUES('one','unsaved WAL content')");conn.commit()
            self.assertGreater(source.with_name(source.name+'-wal').stat().st_size,0)
            before=database_inventory(source);consistent_copy(source,destination)
            self.assertEqual(before,database_inventory(destination));self.assertEqual(conn.execute('SELECT content FROM drafts').fetchone()[0],'unsaved WAL content');conn.close()
    def test_existing_backup_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'db';target=Path(directory)/'backup';target.write_bytes(b'valuable')
            with self.assertRaises(ValueError):consistent_copy(source,target)
            self.assertEqual(target.read_bytes(),b'valuable')
    def test_key_inventory_reports_presence_only_and_long_paths_remain_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'deepseek.credentials.enc').write_bytes(b'opaque-ciphertext')
            from scripts.install_inventory import filesystem_path
            long=root/('a'*90)/('b'*90)/('c'*90);filesystem_path(long).mkdir(parents=True)
            filesystem_path(long/'context.json').write_text('preserve',encoding='utf-8')
            inventory=tree_inventory(root);self.assertEqual(inventory['deepseek.credentials.enc'],{'exists':True})
            self.assertTrue(any(k.endswith('context.json') for k in inventory))
            filesystem_path(long/'context.json').unlink();filesystem_path(long).rmdir()
