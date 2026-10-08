from __future__ import annotations

import json
import hashlib
import uuid
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .catalog import APP_DIR, DATA_DIR, PROJECT_ROOT, COLLECTIONS, COLLECTION_MAP, DEFAULT_COLLECTION, TYPE_NAMES, CatalogDB
from .runtime import HOME, RESOURCES, latex_path
from .assets import image_references, asset_path
from .tex_layout import RENDER_VERSION,subpart_paragraphs
from .compile_queue import CompileScheduler, CompileCancelled
from .render_archive import staged_archive, resource_hashes


EXPORT_DIR = Path(os.environ.get("QUESTION_VIEWER_EXPORT_DIR", HOME / "output"))
CACHE_DIR = Path(os.environ.get("QUESTION_VIEWER_CACHE_DIR", HOME / ".cache" / "previews"))
SOURCE_PREAMBLE = RESOURCES / "preamble.tex"
_processes: set[subprocess.Popen] = set()
_process_lock = threading.Lock()
_stopping = threading.Event()
compiler = CompileScheduler()


def start_compilations():
    _stopping.clear()
    compiler.start()


def cancel_compilations():
    _stopping.set()
    with _process_lock:
        for process in list(_processes):
            if process.poll() is None:
                process.kill()
    compiler.stop()


def export_names(collection_code: str) -> dict[str, str]:
    if collection_code not in COLLECTION_MAP:
        raise ValueError('题库集合不存在')
    if collection_code == 'misc':
        return {'question': '其他专题数学题目册.pdf', 'solution': '其他专题数学解析册.pdf'}
    title = COLLECTION_MAP[collection_code][1]
    return {'question': f'{title}数学难题整理_题目册.pdf', 'solution': f'{title}数学难题整理_答案解析册.pdf'}


def active_export_dir(collection_code: str = DEFAULT_COLLECTION) -> Path | None:
    export_names(collection_code)  # Validate before constructing a path.
    try:
        pointer = EXPORT_DIR / f'current-{collection_code}.json'
        generation = json.loads(pointer.read_text('utf-8'))['generation']
        if not isinstance(generation, str) or not re.fullmatch(r'book-[a-zA-Z0-9-]+', generation):
            return None
        candidate = EXPORT_DIR / 'versions' / collection_code / generation
        if not candidate.resolve().is_relative_to((EXPORT_DIR / 'versions' / collection_code).resolve()):
            return None
        manifest = json.loads((candidate / 'export_manifest.json').read_text('utf-8'))
        if manifest.get('collection_code') != collection_code:
            return None
        if not all((candidate / name).is_file() for name in export_names(collection_code).values()):
            return None
        return candidate
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sanitise(text: Any) -> str:
    text = str(text or "")
    mapping = {
        "∈": r"\in", "∉": r"\notin", "⊆": r"\subseteq", "⊂": r"\subset",
        "∪": r"\cup", "∩": r"\cap", "∅": r"\varnothing", "≤": r"\le",
        "≥": r"\ge", "≠": r"\ne", "∞": r"\infty", "α": r"\alpha",
        "β": r"\beta", "θ": r"\theta", "φ": r"\varphi", "ω": r"\omega",
        "π": r"\pi", "Δ": r"\Delta", "ℝ": r"\mathbb{R}", "ℕ": r"\mathbb{N}",
        "ℤ": r"\mathbb{Z}", "×": r"\times", "÷": r"\div", "∥": r"\parallel",
        "⊥": r"\perp", "⇒": r"\Rightarrow", "⇔": r"\Leftrightarrow",
        "∀": r"\forall", "∃": r"\exists", "∠": r"\angle", "△": r"\triangle",
    }
    for char, latex in mapping.items():
        text = text.replace(char, r"\ensuremath{" + latex + "}")
    text = text.replace("\u200b", "").replace("\ufeff", "").replace("\u00a0", " ")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = text.replace(r"\sqrt[]", r"\sqrt")
    text = re.sub(r"\\\[(.*?)\\\]", lambda m: r"\begin{mathblock}" + m.group(1) + r"\end{mathblock}", text, flags=re.S)
    # A control word immediately followed by Chinese text must be delimited.
    text = text.replace(r"\noindent", r"\noindent ")
    return text


def escape_text(text: Any) -> str:
    return "".join({"&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_", "$": r"\$", "{": r"\{", "}": r"\}", "\\": r"\textbackslash{}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}.get(c, c) for c in str(text or ""))


def source_label(question: dict[str, Any]) -> str:
    sources = question.get("sources") or {}
    origins = sources.get("origins") if isinstance(sources, dict) else []
    if not origins:
        return ""
    labels = []
    for origin in origins:
        if isinstance(origin, dict):
            title = str(origin.get("title") or origin.get("paper_id") or "来源").strip()
            number = origin.get("original_number")
        elif isinstance(origin, str):
            title, number = origin.strip(), None
        else:
            raise ValueError('来源记录无法识别，请在题源表单中修正。')
        if not title:
            title = "来源"
        labels.append(title + (f"第{number}题" if number not in (None, "") else ""))
    return "；".join(labels)


def choices_tex(options: list[str]) -> str:
    opts = [sanitise(x) for x in options]
    if len(opts) != 4:
        return ""
    if any(r"\includegraphics" in item or r"\par" in item for item in opts):
        return "\n".join(r"\par\noindent " + chr(65 + index) + ". " + item for index, item in enumerate(opts))
    return r"\choices" + "".join("{" + item + "}" for item in opts)


def question_block(question: dict[str, Any], number: int, solutions: bool, single: bool = False, source_override: str | None = None) -> str:
    qtype = TYPE_NAMES.get(question.get("type"), question.get("type", "题目"))
    heading = rf"\qheading{{{number}}}{{{qtype}}}{{{escape_text(source_label(question) if source_override is None else source_override)}}}"
    render=lambda value:sanitise(subpart_paragraphs(value) if question.get('type')=='long' else value)
    if solutions:
        answer = question.get("answer_tex", "")
        body = (r"{\heiti 答案：}" + render(answer) + r"\par" if answer else "")
        body += "\n" + render(question.get("solution_tex", ""))
        return heading + "\n" + body
    body = render(question.get("question_tex", ""))
    choice = choices_tex(question.get("options", []))
    if choice:
        body += "\n" + choice
    working = "" if single or question.get("type") != "long" else r"\workingspace"
    return "\n".join([r"\begin{questionbody}", heading, body, r"\end{questionbody}", working])


def _preamble_path_text(path: Path) -> str:
    return path.resolve().as_posix()


def single_document(question: dict[str, Any], solutions: bool = False) -> str:
    return "\n".join(
        [
            r"\input{preamble.tex}",
            rf"\graphicspath{{{{{_preamble_path_text(DATA_DIR)}/}}}}",
            r"\newcommand{\bookvariant}{单题预览}",
            r"\begin{document}",
            r"\pagestyle{empty}",
            question_block(question, int(question.get("position", 1)), solutions, single=True),
            r"\end{document}",
        ]
    )


def full_document(snapshot: list[dict[str, Any]], solutions: bool, collection_code: str = DEFAULT_COLLECTION,
                  asset_root: Path | None = None, include_empty: bool = True) -> tuple[str, list[dict[str, Any]]]:
    if collection_code not in COLLECTION_MAP:
        raise ValueError('题库集合不存在')
    allowed_points = {point for _, _, points in COLLECTION_MAP[collection_code][4] for point, _ in points}
    if any(q.get('collection_code', DEFAULT_COLLECTION) != collection_code or q['point_code'] not in allowed_points for q in snapshot):
        raise ValueError('导出快照包含其他集合的题目')
    by_point: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    manifest: list[dict[str, Any]] = []
    for global_number, question in enumerate(snapshot, 1):
        by_point.setdefault(question["point_code"], []).append((global_number, question))
        manifest.append(
            {
                "collection_code": collection_code,
                "global_number": global_number,
                "id": question["id"],
                "legacy_uid": question.get("legacy_uid"),
                "point_code": question["point_code"],
                "local_number": question["position"],
                "type": question["type"],
                "revision": question["revision"],
            }
        )
    variant = "答案解析册" if solutions else "题目册"
    collection = COLLECTION_MAP[collection_code]
    lines = [
        r"\input{preamble.tex}",
        r"\graphicspath{{./}}" if asset_root is not None else rf"\graphicspath{{{{{_preamble_path_text(DATA_DIR)}/}}}}",
        rf"\newcommand{{\bookvariant}}{{{variant}}}",
        rf"\renewcommand{{\collectiontitle}}{{{escape_text('其他专题' if collection_code == 'misc' else collection[1])}}}",
        rf"\renewcommand{{\collectionmaterial}}{{{escape_text(collection[2])}}}",
        r"\hypersetup{pdftitle={" + escape_text(collection[1] + " " + variant) + r"},pdfsubject={" + escape_text(collection[1]) + "}}",
        r"\begin{document}",
        rf"\bookcover{{{variant}}}{{{len(snapshot)}}}",
        r"\frontmatter",
        r"\tableofcontents",
        r"\mainmatter",
    ]
    for _, topic_title, points in collection[4]:
        if not include_empty and not any(by_point.get(code) for code,_ in points):continue
        lines.append(r"\chapter{" + topic_title + "}")
        lines.append(r"\markboth{" + topic_title + "}{}")
        for point_code, point_title in points:
            if not include_empty and not by_point.get(point_code):continue
            lines.append(r"\section{" + point_title + "}")
            entries = by_point.get(point_code, [])
            if not entries:
                lines.append(r"{\small\color{muted}当前题库中暂无此考点。}\par")
            for global_number, question in entries:
                lines.append(rf"\hypertarget{{q{global_number}}}{{}}")
                lines.append(question_block(question, global_number, solutions))
    lines.append(r"\end{document}")
    return "\n\n".join(lines), manifest


class LatexError(Exception):
    pass


def compile_tex(tex_source: str, output_name: str = "preview", timeout: int = 90, passes: int = 1,
                *, resource_root: Path | None = None, priority: int = 0) -> bytes:
    job = compiler.submit(lambda cancelled: _compile_tex_unlocked(
        tex_source, output_name, timeout, passes, resource_root, cancelled), priority=priority)
    return job.future.result()


def submit_preview(tex_source: str, session: str | None, revision: int):
    return compiler.submit(lambda cancelled: _compile_tex_unlocked(
        tex_source, 'preview', 90, 1, None, cancelled), priority=1, session=session, revision=revision)


def _compile_tex_unlocked(tex_source: str, output_name: str, timeout: int, passes: int,
                          resource_root: Path | None = None, cancelled: threading.Event | None = None) -> bytes:
    cancelled = cancelled or threading.Event()
    if cancelled.is_set():
        raise CompileCancelled('预览已过期或取消')
    if os.environ.get("QUESTION_VIEWER_SKIP_LATEX_VALIDATION") == "1":
        return b"%PDF-1.4\n% test placeholder\n"
    executable = latex_path()
    if not executable or not Path(executable).is_file():
        raise LatexError('未找到 XeLaTeX，请在设置中选择 xelatex.exe。')
    if _stopping.is_set():
        raise LatexError('应用正在退出，编译已停止。')
    template = resource_root/'preamble.tex' if resource_root else SOURCE_PREAMBLE
    if not template.exists():
        raise LatexError(f"未找到排版模板：{template}")
    with tempfile.TemporaryDirectory(prefix="question-viewer-") as raw_dir:
        work = Path(raw_dir)
        shutil.copy2((resource_root/'preamble.tex') if resource_root else SOURCE_PREAMBLE, work / "preamble.tex")
        if resource_root and (resource_root/'assets').exists():
            shutil.copytree(resource_root/'assets', work/'assets')
        (work / f"{output_name}.tex").write_text(tex_source, encoding="utf-8")
        command = [
            executable,
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            f"{output_name}.tex",
        ]
        env = os.environ.copy()
        env["TEXINPUTS"] = str(work if resource_root else DATA_DIR) + os.pathsep + ('' if resource_root else env.get("TEXINPUTS", ""))
        output = ""
        for _ in range(passes):
            try:
                with _process_lock:
                    if _stopping.is_set() or cancelled.is_set():
                        raise LatexError('编译已停止。')
                    process = subprocess.Popen(command, cwd=work, env=env, stdout=subprocess.PIPE,
                                               stderr=subprocess.STDOUT,
                                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    _processes.add(process)
                deadline = time.monotonic() + timeout
                while True:
                    if cancelled.is_set():
                        process.kill()
                        process.communicate()
                        raise CompileCancelled('预览已过期或取消')
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    try:
                        raw_output, _ = process.communicate(timeout=min(.1, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        continue
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()
                raise LatexError("LaTeX 编译超时") from exc
            finally:
                with _process_lock:
                    if 'process' in locals():
                        _processes.discard(process)
            output = raw_output.decode("utf-8", errors="replace")
            if process.returncode:
                meaningful = [line for line in output.splitlines() if "error" in line.lower() or line.startswith("!") or ".tex:" in line]
                raise LatexError("\n".join(meaningful[-12:]) or "LaTeX 编译失败")
        pdf = work / f"{output_name}.pdf"
        if not pdf.exists():
            raise LatexError("LaTeX 未生成 PDF")
        return pdf.read_bytes()


def validate_question(question: dict[str, Any]) -> None:
    if question.get("type") not in TYPE_NAMES:
        raise ValueError("题型无效")
    if not str(question.get("question_tex", "")).strip():
        raise ValueError("题干不能为空")
    if not str(question.get("solution_tex", "")).strip():
        raise ValueError("答案解析不能为空")
    options = question.get("options") or []
    if question["type"] in {"single", "multi"}:
        if len(options) != 4 or any(not str(option).strip() for option in options):
            raise ValueError("单选题和多选题必须填写四个非空选项")
    elif options:
        raise ValueError("填空题和解答题不能包含选择题选项")
    for relative in image_references(question):
        asset_path(DATA_DIR, relative)


def cached_question_pdf(db: CatalogDB, question_id: str, view: str) -> Path:
    question = db.get_question(question_id)
    if not question:
        raise KeyError(question_id)
    solutions = view == "solution"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    source = single_document(question, solutions)
    digest = hashlib.sha256((str(RENDER_VERSION)+source).encode('utf-8'))
    digest.update(SOURCE_PREAMBLE.read_bytes())
    for ref in sorted(image_references(question)):
        digest.update(ref.encode('utf-8'))
        digest.update(asset_path(DATA_DIR, ref).read_bytes())
    target = CACHE_DIR / f"{question_id}-{digest.hexdigest()}-{view}.pdf"
    if not target.exists():
        content = compile_tex(source, "preview", priority=1)
        temporary = target.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_bytes(content)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return target



class ExportManager:
    """One serial compiler; independent pointers and freshness for each collection.

    Data mutations only invalidate exports. Startup and edits never queue a full
    library export; an explicit user request always names exactly one collection.
    """
    def __init__(self, db: CatalogDB) -> None:
        self.db = db
        self._event = threading.Event()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._statuses: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, tuple] = {}

    file_names = staticmethod(export_names)

    def _stored_status(self, code):
        if code not in self._statuses:
            state = {'state': 'idle', 'stale': True, 'message': '尚未生成，请导出当前集合',
                     'updated_at': None, 'catalog_revision': None, 'collection_revision': None,
                     'count': 0, 'error': None, 'collection_code': code}
            folder = active_export_dir(code)
            if folder:
                try:
                    manifest = json.loads((folder / 'export_manifest.json').read_text('utf8'))
                    state.update(state='ready', message='导出完成', updated_at=manifest['generated_at'],
                                 collection_revision=manifest['collection_revision'],
                                 catalog_revision=manifest['collection_revision'], count=manifest['count'],render_version=manifest.get('render_version'))
                except (OSError, ValueError, KeyError):
                    pass
            self._statuses[code] = state
        return self._statuses[code]

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, name='latex-export-worker', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            self._pending.clear()
        self._event.set()

    def invalidate(self, *collection_codes):
        for code in set(collection_codes):
            export_names(code)
            with self._lock:
                state = self._stored_status(code)
                state.update(stale=True)
                if state['state'] not in ('building', 'pending'):
                    state.update(state='idle', message='题库已更新，请导出当前集合', error=None)

    def schedule(self, collection_code=DEFAULT_COLLECTION):
        revision, count = self.db.collection_state(collection_code)
        if not count:
            with self._lock:
                self._stored_status(collection_code).update(state='failed', stale=True,
                    message='当前集合暂无题目，无法生成 PDF', error='当前集合暂无题目，无法生成 PDF')
            raise ValueError('当前集合暂无题目，无法生成 PDF')
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError('应用正在退出，不能启动导出')
            state = self._stored_status(collection_code)
            if state['state'] not in ('pending', 'building'):
                frozen = self.db.collection_snapshot(collection_code)
                if not frozen[1]:
                    raise ValueError('当前集合暂无题目，无法生成 PDF')
                self._pending[collection_code] = frozen
                state.update(state='pending', message='等待编译当前集合', error=None)
            self._event.set()
        return self.status(collection_code)

    def status(self, collection_code=DEFAULT_COLLECTION):
        revision, count = self.db.collection_state(collection_code)
        with self._lock:
            status = dict(self._stored_status(collection_code))
        available = active_export_dir(collection_code) is not None
        stale = not available or status['collection_revision'] != revision or status['state'] == 'failed' or status.get('render_version')!=RENDER_VERSION
        if available and status.get('render_version')!=RENDER_VERSION:status['message']='排版规则已更新，请重新生成；上一成功版本仍可读取'
        status.update(stale=stale, available=available, current_count=count,
                      current_revision=revision, collection_title=COLLECTION_MAP[collection_code][1])
        if stale and status['state'] == 'ready':
            status.update(state='idle', message='题库已更新，请导出当前集合')
        names = export_names(collection_code)
        for kind, filename in names.items():
            status[f'{kind}_filename'] = filename
            status[f'{kind}_pdf'] = f'/exports/{filename}?collection_code={collection_code}'
        return status

    def _worker(self):
        while not self._stop.is_set():
            self._event.wait()
            with self._lock:
                if self._stop.is_set():
                    return
                code = next(iter(self._pending), None)
                if code is None:
                    self._event.clear()
                    continue
                frozen = self._pending.pop(code)
                if not self._pending:
                    self._event.clear()
            self._run_export(code, frozen)

    def _run_export(self, collection_code=DEFAULT_COLLECTION, frozen=None):
        export_names(collection_code)
        with self._lock:
            self._stored_status(collection_code).update(state='building', message='正在生成当前集合题目册和解析册', error=None)
        try:
            revision, snapshot, assets, preamble = frozen or self.db.collection_snapshot(collection_code)
            if not snapshot:
                raise LatexError('当前集合暂无题目，无法生成 PDF')
            generation = 'book-' + uuid.uuid4().hex
            folder = EXPORT_DIR / 'versions' / collection_code / generation
            with staged_archive(folder, assets, preamble) as stage:
                question_tex, manifest = full_document(snapshot, False, collection_code, asset_root=stage)
                solution_tex, solution_manifest = full_document(snapshot, True, collection_code, asset_root=stage)
                assert manifest == solution_manifest
                for item, question in zip(manifest, snapshot):
                    item['content_sha256'] = hashlib.sha256(json.dumps(question, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
                meta = COLLECTION_MAP[collection_code]
                payload = {'format_version': 3, 'collection_code': collection_code, 'collection_title': meta[1],
                           'collection_material': meta[2], 'collection_revision': revision, 'catalog_revision': revision,
                           'generated_at': _stamp(), 'count': len(snapshot), 'questions': manifest,
                           'render_version':RENDER_VERSION, **resource_hashes(assets, preamble)}
                names = export_names(collection_code)
                outputs = {names['question']: compile_tex(question_tex, 'questions', timeout=600, passes=2, resource_root=stage, priority=2),
                           names['solution']: compile_tex(solution_tex, 'solutions', timeout=600, passes=2, resource_root=stage, priority=2),
                           'questions.tex': question_tex.encode('utf-8'), 'solutions.tex': solution_tex.encode('utf-8'),
                           'export_manifest.json': json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')}
                if self._stop.is_set():
                    raise LatexError('应用正在退出，导出已停止。')
                for name, content in outputs.items():
                    (stage / name).write_bytes(content)
            with self._lock:
                if self._stop.is_set():
                    return
                pointer = EXPORT_DIR / f'current-{collection_code}.tmp'
                pointer.write_text(json.dumps({'generation': generation}), 'utf-8')
                os.replace(pointer, EXPORT_DIR / f'current-{collection_code}.json')
                self._stored_status(collection_code).update(state='ready', message='导出完成',render_version=RENDER_VERSION,
                    updated_at=payload['generated_at'], catalog_revision=revision,
                    collection_revision=revision, count=len(snapshot), error=None)
        except Exception as exc:
            with self._lock:
                self._stored_status(collection_code).update(state='failed', stale=True,
                    message='导出失败，已保留上一成功版本', error=str(exc), updated_at=_stamp())
