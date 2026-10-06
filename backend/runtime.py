from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import uuid
from contextlib import closing
from pathlib import Path

APP_VERSION = os.environ.get('QD_APP_VERSION') or json.loads((Path(__file__).resolve().parents[1]/'package.json').read_text('utf-8')).get('version','unknown') if not getattr(__import__('sys'),'frozen',False) else os.environ.get('QD_APP_VERSION','unknown')
APP_ROOT = Path(__file__).resolve().parents[1]
HOME = Path(os.environ.get('QD_HOME', APP_ROOT / 'runtime')).resolve()
RESOURCES = Path(os.environ.get('QD_RESOURCES', APP_ROOT / 'resources')).resolve()
FRONTEND = Path(os.environ.get('QD_FRONTEND', APP_ROOT / 'frontend/dist')).resolve()
SETTINGS = HOME / 'data/settings.json'
_settings_lock = threading.RLock()
_settings_warnings: dict[str, str] = {}


def initialize_seed():
    """Populate a new portable data directory, never replace a user's database."""
    data = HOME / 'data'
    data.mkdir(parents=True, exist_ok=True)
    for name in ['logs', 'output', '.cache']:
        (HOME / name).mkdir(parents=True, exist_ok=True)
    probe = HOME / '.write-test'
    probe.write_text('ok')
    probe.unlink()
    target = data / 'question_bank.sqlite3'
    if target.exists():
        return
    seed = RESOURCES / 'seed'
    if not (seed / 'question_bank.sqlite3').is_file():
        raise RuntimeError('初始题库缺失，请重新解压完整应用文件夹。')
    shutil.copytree(seed / 'assets', data / 'assets', dirs_exist_ok=True)
    temporary = data / 'question_bank.sqlite3.initializing'
    with closing(sqlite3.connect((seed / 'question_bank.sqlite3').as_uri() + '?mode=ro&immutable=1', uri=True)) as src, closing(sqlite3.connect(temporary)) as dst:
        src.backup(dst)
    os.replace(temporary, target)


def _settings_value(path: Path) -> dict:
    value = json.loads(path.read_text('utf-8'))
    if not isinstance(value, dict) or not isinstance(value.get('xelatex_path', ''), str):
        raise ValueError('设置格式无效')
    return value


def _atomic_settings(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as output:
            output.write(json.dumps(value, ensure_ascii=False, indent=2))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_settings():
    with _settings_lock:
        key = str(SETTINGS)
        damaged = False
        if SETTINGS.exists():
            try:
                return _settings_value(SETTINGS)
            except (ValueError, UnicodeError):
                damaged = True
                preserved = SETTINGS.with_name('settings.corrupt-' + uuid.uuid4().hex + '.json')
                os.replace(SETTINGS, preserved)
                _settings_warnings[key] = '设置文件损坏，已保留损坏副本。'
        backup = SETTINGS.with_suffix('.json.bak')
        recovered = {}
        if backup.exists():
            try:
                recovered = _settings_value(backup)
                _settings_warnings[key] = _settings_warnings.get(key, '') + '已恢复最近有效设置，请保存确认。'
            except (ValueError, UnicodeError):
                _settings_warnings[key] = '设置及备份无效，已使用默认设置，请重新保存。'
        elif damaged:
            _settings_warnings[key] += '已使用默认设置，请重新保存。'
        if damaged or backup.exists():
            _atomic_settings(SETTINGS, recovered)
        return recovered


def set_latex_path(path: str):
    path = path.strip().strip('"')
    if path and (Path(path).name.lower() != 'xelatex.exe' or not Path(path).is_file()):
        raise ValueError('请选择有效的 xelatex.exe 文件，或清空路径以自动检测。')
    with _settings_lock:
        settings = read_settings()
        settings['xelatex_path'] = path
        _atomic_settings(SETTINGS, settings)
        _atomic_settings(SETTINGS.with_suffix('.json.bak'), settings)
        _settings_warnings.pop(str(SETTINGS), None)


def latex_path():
    configured = read_settings().get('xelatex_path', '')
    return configured or os.environ.get('XELATEX') or shutil.which('xelatex') or ''


def latex_status():
    resolved = latex_path()
    available = bool(resolved and Path(resolved).is_file())
    warning = _settings_warnings.get(str(SETTINGS), '')
    return {'path': resolved, 'configured_path': read_settings().get('xelatex_path', ''), 'warning': warning,
            'available': available,
            'message': warning + ('已找到 XeLaTeX，可运行编译测试' if available else '未找到 XeLaTeX，请在设置中选择 xelatex.exe。')}
