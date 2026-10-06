import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BOOT = tempfile.TemporaryDirectory(prefix='question-tests-bootstrap-')
os.environ['QD_HOME'] = BOOT.name
os.environ['QD_RESOURCES'] = str(ROOT / 'resources')
os.environ.pop('QUESTION_VIEWER_SKIP_LATEX_VALIDATION', None)

from backend import catalog, runtime, latex_service, papers


def payload(**changes):
    return {
        'collection_code': 'gaoyi-second', 'point_code': '6.1', 'position': 1,
        'type': 'fill', 'question_tex': r'计算 $1+1$。', 'options': [],
        'answer_tex': '2', 'solution_tex': r'$1+1=2$。',
        'sources': {'origins': [{'title': '隔离回归测试'}]}, 'verified': False,
        **changes,
    }


class IsolatedCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='question-regression-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.data = self.home / 'data'
        self.data.mkdir()
        shutil.copytree(ROOT / 'resources/seed/assets', self.data / 'assets')
        seed = ROOT / 'resources/seed/question_bank.sqlite3'
        with sqlite3.connect(seed.as_uri() + '?mode=ro&immutable=1', uri=True) as source:
            with sqlite3.connect(self.data / 'question_bank.sqlite3') as target:
                source.backup(target)
        source.close()
        target.close()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(catalog, DATA_DIR=self.data, ASSET_DIR=self.data/'assets'))
        self.stack.enter_context(patch.multiple(runtime, HOME=self.home, SETTINGS=self.data/'settings.json'))
        self.stack.enter_context(patch.multiple(latex_service, DATA_DIR=self.data,
            EXPORT_DIR=self.home/'output', CACHE_DIR=self.home/'.cache/previews'))
        self.stack.enter_context(patch.object(papers, 'PAPERS_DIR', self.home/'output/papers'))
        self.db = catalog.CatalogDB(self.data/'question_bank.sqlite3')
        self.db.initialize()

    def create(self, **changes):
        return self.db.create_question(payload(**changes))[1]

    def draft(self, question, **form_changes):
        form = {**question, **form_changes}
        return {'form': form, 'source_rows': []}
