from __future__ import annotations
from .tex_layout import RENDER_VERSION

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog import CatalogDB
from .latex_service import EXPORT_DIR, compile_tex, question_block, source_label
from .runtime import RESOURCES
from .render_archive import staged_archive, resource_hashes


PAPERS_DIR = EXPORT_DIR / 'papers'


def active_paper_dir() -> Path | None:
    try:
        generation = json.loads((PAPERS_DIR / 'current.json').read_text('utf-8'))['generation']
        if not isinstance(generation, str) or not re.fullmatch(r'paper-[a-f0-9]{32}', generation):
            return None
        folder = PAPERS_DIR / 'versions' / generation
        if not folder.resolve().is_relative_to((PAPERS_DIR / 'versions').resolve()):
            return None
        manifest = json.loads((folder / 'paper_manifest.json').read_text('utf-8'))
        names = manifest['files']
        if manifest.get('generation') != generation or not all(
            isinstance(names.get(kind), str) and re.fullmatch(r'高中数学训练卷_\d{8}-\d{6}_' + ('题目卷' if kind == 'question' else '解析卷') + r'\.pdf', names[kind])
            and (folder / names[kind]).is_file() for kind in ('question', 'solution')
        ):
            return None
        return folder
    except (OSError, ValueError, KeyError, TypeError):
        return None


def paper_document(snapshot: list[dict[str, Any]], solutions: bool, asset_root: Path) -> str:
    variant = '解析卷' if solutions else '题目卷'
    lines = [r'\input{preamble.tex}',
             r'\graphicspath{{./}}',
             rf'\newcommand{{\bookvariant}}{{{variant}}}',
             r'\hypersetup{pdftitle={高中数学训练卷' + variant + r'}}',
             r'\begin{document}',
             r'\begin{titlepage}\thispagestyle{empty}\vspace*{35mm}',
             r'{\heiti\fontsize{28}{40}\selectfont 高中数学训练卷\par}',
             rf'\vspace{{16mm}}{{\heiti\zihao{{2}}{variant}\par}}',
             rf'\vfill{{\zihao{{4}}共 {len(snapshot)} 题\par}}',
             r'\end{titlepage}']
    for number, question in enumerate(snapshot, 1):
        location = f"{question['collection_title']} / {question['topic_title']} / {question['point_title']} / 第 {question['position']} 题"
        label = ' · '.join(part for part in (source_label(question), location) if part) if solutions else ''
        lines.append(question_block(question, number, solutions, source_override=label))
    lines.append(r'\end{document}')
    return '\n\n'.join(lines)


class PaperManager:
    def __init__(self, db: CatalogDB) -> None:
        self.db = db
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {'state': 'idle', 'message': '尚未生成训练卷', 'error': None}
        self._stopping = False

    def stop(self):
        with self._lock:
            self._stopping = True

    def status(self):
        with self._lock:
            state = dict(self._state)
        folder = active_paper_dir()
        state['available'] = folder is not None
        if folder:
            manifest = json.loads((folder / 'paper_manifest.json').read_text('utf-8'))
            state.update(stale=manifest.get('render_version')!=RENDER_VERSION,render_version=manifest.get('render_version'),generation=manifest['generation'], generated_at=manifest['generated_at'],
                         count=manifest['count'], files=manifest['files'])
            if state['state'] == 'idle':
                state.update(state='ready', message='最近一次训练卷已生成')
            if state['stale']:state['message']='排版规则已更新，请重新生成训练卷；旧成功版本仍可读取'
        else:
            state.update(generation=None, generated_at=None, count=0, files={})
        return state

    def schedule(self, mode: str, question_ids=None, count=None):
        with self._lock:
            if self._stopping:
                raise RuntimeError('应用正在退出，不能开始组卷')
            if self._thread and self._thread.is_alive():
                raise RuntimeError('已有训练卷正在编译，请稍后重试')
            snapshot, assets, preamble = self.db.paper_render_snapshot(mode, question_ids, count)
            self._state.update(state='pending', message='已固定题目快照，等待编译', error=None)
            self._thread = threading.Thread(target=self._run, args=(mode, snapshot, assets, preamble),
                                            name='training-paper-worker', daemon=True)
            self._thread.start()
        return self.status()

    def _run(self, mode, snapshot, assets, preamble=None):
        with self._lock:
            self._state.update(state='building', message='正在编译训练卷题目卷和解析卷')
        try:
            generation = 'paper-' + uuid.uuid4().hex
            folder = PAPERS_DIR / 'versions' / generation
            preamble = preamble if preamble is not None else (RESOURCES/'preamble.tex').read_bytes()
            with staged_archive(folder, assets, preamble) as asset_root:
                question_tex = paper_document(snapshot, False, asset_root)
                solution_tex = paper_document(snapshot, True, asset_root)
                stamp = datetime.now(timezone.utc)
                date = stamp.strftime('%Y%m%d-%H%M%S')
                names = {'question': f'高中数学训练卷_{date}_题目卷.pdf',
                         'solution': f'高中数学训练卷_{date}_解析卷.pdf'}
                question_pdf = compile_tex(question_tex, 'paper-questions', timeout=600, passes=2, resource_root=asset_root, priority=2)
                solution_pdf = compile_tex(solution_tex, 'paper-solutions', timeout=600, passes=2, resource_root=asset_root, priority=2)
                manifest = {'render_version':RENDER_VERSION,
                    'format_version': 2, 'generation': generation, 'mode': mode,
                    'generated_at': stamp.isoformat(timespec='seconds'), 'count': len(snapshot), 'files': names,
                    'questions': [{
                        'global_number': number, 'id': q['id'], 'collection_code': q['collection_code'],
                        'point_code': q['point_code'], 'local_number': q['position'], 'revision': q['revision'],
                        'source': source_label(q),
                        'content_sha256': hashlib.sha256(json.dumps(q, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest(),
                    } for number, q in enumerate(snapshot, 1)],
                    **resource_hashes(assets, preamble),
                }
                if self._stopping:
                    raise RuntimeError('应用正在退出，训练卷已停止。')
                (asset_root / names['question']).write_bytes(question_pdf)
                (asset_root / names['solution']).write_bytes(solution_pdf)
                (asset_root / 'questions.tex').write_text(question_tex, 'utf-8')
                (asset_root / 'solutions.tex').write_text(solution_tex, 'utf-8')
                (asset_root / 'paper_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), 'utf-8')
            with self._lock:
                if self._stopping:
                    return
                pointer = PAPERS_DIR / ('current-' + uuid.uuid4().hex + '.tmp')
                pointer.write_text(json.dumps({'generation': generation}), 'utf-8')
                os.replace(pointer, PAPERS_DIR / 'current.json')
                self._state.update(state='ready', message='训练双卷生成完成', error=None)
        except Exception as exc:
            with self._lock:
                self._state.update(state='failed', message='训练卷生成失败，已保留上次成功版本', error=str(exc))

