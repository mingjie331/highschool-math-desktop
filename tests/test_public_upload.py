"""The public upload boundary must inspect staged bytes, not clean replacements."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts.audit_public_files import path_issue, read_index, scan_secrets, source_candidates, validate_seed
from scripts import release_tools

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT/'scripts/release-manifest.json').read_text('utf-8'))


class PublicUploadTests(unittest.TestCase):
    def test_source_coverage_includes_new_modules_and_undeclared_root_code(self):
        with tempfile.TemporaryDirectory() as area:
            root = Path(area)
            (root/'frontend/src').mkdir(parents=True)
            (root/'frontend/src/new.mjs').write_text('export const value = 1', encoding='utf-8')
            (root/'helper.py').write_text('value = 1', encoding='utf-8')
            paths = source_candidates(root, CONFIG)
            self.assertTrue({'frontend/src/new.mjs', 'helper.py'} <= paths)

    def test_staged_secret_is_found_even_after_working_file_is_cleaned(self):
        with tempfile.TemporaryDirectory() as area:
            root = Path(area)
            subprocess.run(['git', 'init', '-q', '-b', 'main', str(root)], check=True)
            target = root/'settings.py'
            fake = 's'+'k-'+'A'*32
            target.write_text('value = '+repr(fake), encoding='utf-8')
            subprocess.run(['git', '-C', str(root), 'add', 'settings.py'], check=True)
            target.write_text('value = None', encoding='utf-8')
            blobs, issues = read_index(root)
            self.assertFalse(issues)
            found = scan_secrets('settings.py', blobs['settings.py'])
            self.assertEqual(found[0]['rule'], 'provider_key')
            self.assertNotIn(fake, json.dumps(found))

    def test_runtime_database_and_credential_temporary_files_are_rejected(self):
        for name in ['runtime/data/a.sqlite3', '.local/backups/key.credentials.enc',
                     'frontend/src/deepseek.credentials.enc.123.tmp', 'docs/settings.json',
                     'resources/seed/another.sqlite3', 'docs/validation/history.json']:
            with self.subTest(name=name):
                self.assertIsNotNone(path_issue(name, CONFIG))
        self.assertIsNone(path_issue('desktop/agent-secrets.cjs', CONFIG))
        self.assertIsNone(path_issue('resources/seed/question_bank.sqlite3', CONFIG))

    def test_seed_checks_missing_image_and_hash_without_printing_data(self):
        paths = [ROOT/'resources/seed/question_bank.sqlite3', ROOT/'desktop/icon.png', ROOT/'desktop/icon.ico']
        paths += list((ROOT/'resources/seed/assets').glob('*.png'))
        blobs = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in paths}
        summary, issues = validate_seed(blobs, CONFIG)
        self.assertFalse(issues)
        self.assertEqual(summary['questions'], 627)
        removed = next(name for name in blobs if name.startswith('resources/seed/assets/'))
        del blobs[removed]
        wrong_hash = {**CONFIG, 'seed_sha256': '0'*64}
        _, issues = validate_seed(blobs, wrong_hash)
        rules = {issue['rule'] for issue in issues}
        self.assertTrue({'seed_hash_mismatch', 'seed_asset_count', 'missing_or_unsafe_image_reference'} <= rules)

    def test_source_zip_preserves_custom_public_assets_but_omits_private_files(self):
        with tempfile.TemporaryDirectory() as area:
            root = Path(area)
            files = {'frontend/public/custom.txt': 'public asset',
                     'frontend/public/pdfjs/generated.txt': 'generated',
                     'docs/validation/history.json': '{}',
                     'backend/custom.credentials.enc.123.tmp': 'opaque',
                     'resources/seed/private.sqlite3': 'private',
                     'README.md': 'public'}
            for name, value in files.items():
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value, encoding='utf-8')
            config = {**CONFIG, 'source_files': ['README.md']}
            with patch.multiple(release_tools, ROOT=root, CONFIG=config, STAGE=root/'build/stage'):
                archive = release_tools.build_source()
            with zipfile.ZipFile(archive) as zipped:
                self.assertEqual(set(zipped.namelist()), {'question-desktop/README.md', 'question-desktop/frontend/public/custom.txt'})

    def test_token_in_url_is_reported_without_echoing_credentials(self):
        blob = b'https://' + b'user:' + b'temporary-password' + b'@example.invalid/path'
        issues = scan_secrets('config.txt', blob)
        self.assertEqual(issues[0]['rule'], 'credential_in_url')
        self.assertNotIn('temporary-password', json.dumps(issues))
