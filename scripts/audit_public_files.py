"""Audit the exact Git index bytes before public commits; never print secrets."""
from __future__ import annotations

import hashlib
from contextlib import closing
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {'backend', 'frontend', 'desktop', 'resources', 'scripts', 'tests', 'docs'}
PRIVATE_DIRS = {'.git', '.local', '.cache', '.venv', 'node_modules', 'runtime', 'build',
                'release', 'test-results', 'data', 'output', 'logs', '__pycache__', '测试题目'}
SEED = 'resources/seed/question_bank.sqlite3'
PRIVATE_SUFFIXES = {'.pem', '.key', '.p12', '.pfx', '.db', '.log', '.tmp', '.pyc', '.tsbuildinfo'}
TEXT_SUFFIXES = {'.py', '.cjs', '.mjs', '.js', '.jsx', '.ts', '.tsx', '.mts', '.cts', '.svg', '.json', '.css', '.html', '.tex',
                 '.md', '.txt', '.ps1', '.csv', '.toml', '.yml', '.yaml', '.sql'}
SECRET_PATTERNS = {
    'provider_key': re.compile(r'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}'),
    'github_token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})'),
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'aws_access_key': re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    'credential_in_url': re.compile(r'https?://[^\s/@:\"\x27]+:[^\s/@\"\x27]+@'),
    'literal_credential': re.compile(r'(?i)[\"\x27]?(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)[\"\x27]?\s*[:=]\s*[\"\x27]([^\"\x27\r\n]{12,})[\"\x27]'),
}
IMAGE_RE = re.compile(r'\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}')


def git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    result = subprocess.run(['git', '-C', str(root), *args], input=data, capture_output=True)
    if result.returncode:
        raise ValueError('Git command failed; run from an initialized project repository.')
    return result.stdout


def read_index(root: Path) -> tuple[dict[str, bytes], list[dict]]:
    """Read blobs by object ID, rather than scanning changed working-tree files."""
    entries = []
    issues = []
    for record in git(root, 'ls-files', '--stage', '-z').split(b'\0'):
        if not record:
            continue
        meta, name = record.split(b'\t', 1)
        mode, oid, stage = meta.decode('ascii').split()
        path = name.decode('utf-8')
        if stage != '0' or mode not in {'100644', '100755'}:
            issues.append({'file': path, 'rule': 'conflict_symlink_or_submodule'})
        else:
            entries.append((path, oid))
    if not entries:
        raise ValueError('Git index is empty. Stage the public source files first.')
    response = io.BytesIO(git(root, 'cat-file', '--batch', data=('\n'.join(oid for _, oid in entries)+'\n').encode('ascii')))
    blobs = {}
    for path, oid in entries:
        header = response.readline().decode('ascii').strip().split()
        if len(header) != 3 or header[0] != oid or header[1] != 'blob':
            raise ValueError('Invalid index object response.')
        size = int(header[2])
        content = response.read(size)
        if len(content) != size or response.read(1) != b'\n':
            raise ValueError('Incomplete index object response.')
        blobs[path] = content
    return blobs, issues


def excluded_path(path: str, config: dict) -> bool:
    parts = PurePosixPath(path).parts
    return bool(set(parts) & (PRIVATE_DIRS | set(config.get('source_excluded', [])))) or any(
        path == item or path.startswith(item+'/')
        for item in config.get('source_excluded_paths', []))


def path_issue(path: str, config: dict) -> str | None:
    p = PurePosixPath(path)
    parts = p.parts
    lower = path.lower()
    if not parts or p.is_absolute() or '..' in parts or ':' in path or '\\' in path:
        return 'unsafe_path'
    if excluded_path(path, config) or lower.startswith(('docs/validation/', 'frontend/dist/', 'frontend/public/pdfjs/')):
        return 'private_or_generated_directory'
    if p.name.lower().startswith('.env') or '.credentials.enc' in lower or p.name.lower() in {'.npmrc', '.pypirc', 'local state', 'settings.json'}:
        return 'credential_or_machine_configuration'
    if p.suffix.lower() in PRIVATE_SUFFIXES or lower.endswith(('-wal', '-shm')):
        return 'private_or_generated_file'
    if '.sqlite3' in lower and path != SEED:
        return 'non_seed_database'
    if len(parts) == 1:
        if path not in config['source_files']:
            return 'undeclared_root_file'
    elif parts[0] not in DIRECTORIES:
        return 'undeclared_source_directory'
    if path == SEED or path in {'desktop/icon.png', 'desktop/icon.ico'}:
        return None
    if path.startswith('resources/seed/assets/') and p.suffix.lower() in {'.png', '.jpg', '.jpeg'}:
        return None
    if p.suffix.lower() not in TEXT_SUFFIXES and path not in {'.gitignore', '.gitattributes', 'LICENSE', 'NOTICE'}:
        return 'unreviewed_file_type'
    return None


def source_candidates(root: Path, config: dict) -> set[str]:
    """Detect source/resources present locally but omitted from the index."""
    candidates = set(config['source_files'])
    for file in root.iterdir():
        if file.is_file() and file.suffix.lower() in TEXT_SUFFIXES and path_issue(file.name, config) == 'undeclared_root_file':
            candidates.add(file.name)
    for folder in config['source_directories']:
        for current, dirs, names in os.walk(root/folder):
            rel = Path(current).relative_to(root)
            dirs[:] = [name for name in dirs if not excluded_path((rel/name).as_posix(), config)]
            for name in names:
                path = (rel/name).as_posix()
                if path_issue(path, config) in {None, 'unreviewed_file_type'}:
                    candidates.add(path)
    return candidates


def scan_secrets(path: str, content: bytes) -> list[dict]:
    value = content.decode('utf-8', errors='replace')
    issues = []
    for rule, pattern in SECRET_PATTERNS.items():
        for match in pattern.finditer(value):
            issues.append({'file': path, 'line': value.count('\n', 0, match.start())+1, 'rule': rule})
    return issues


def validate_seed(blobs: dict[str, bytes], config: dict) -> tuple[dict, list[dict]]:
    issues = []
    content = blobs.get(SEED)
    if content is None:
        return {}, [{'file': SEED, 'rule': 'missing_seed'}]
    digest = hashlib.sha256(content).hexdigest()
    if digest != config['seed_sha256']:
        issues.append({'file': SEED, 'rule': 'seed_hash_mismatch'})
    asset_paths = {name for name in blobs if name.startswith('resources/seed/assets/')}
    refs = set()
    # The seed uses a WAL header. Inspect exact staged bytes in an immutable
    # temporary file; deserializing such a header into :memory: is not portable.
    with tempfile.TemporaryDirectory(prefix='public-index-seed-') as area:
        snapshot = Path(area)/'seed.sqlite3'
        snapshot.write_bytes(content)
        with closing(sqlite3.connect(snapshot.as_uri()+'?mode=ro&immutable=1', uri=True)) as conn:
            integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
            count = conn.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
            for row in conn.execute('SELECT question_tex,answer_tex,solution_tex,options_json FROM questions'):
                fields = list(row[:3])+json.loads(row[3])
                refs.update(name.replace('\\', '/').strip() for name in IMAGE_RE.findall('\n'.join(fields)))
    if integrity != 'ok' or count != config['seed_question_count']:
        issues.append({'file': SEED, 'rule': 'seed_integrity_or_count'})
    if len(asset_paths) != config['seed_asset_count']:
        issues.append({'file': 'resources/seed/assets', 'rule': 'seed_asset_count'})
    for ref in sorted(refs):
        if '..' in PurePosixPath(ref).parts or ':' in ref or not ref.startswith('assets/') or 'resources/seed/'+ref not in blobs:
            issues.append({'file': SEED, 'rule': 'missing_or_unsafe_image_reference'})
    from PIL import Image
    for path in sorted(asset_paths | {'desktop/icon.png', 'desktop/icon.ico'}):
        if path not in blobs:
            issues.append({'file': path, 'rule': 'missing_image'})
            continue
        try:
            with Image.open(io.BytesIO(blobs[path])) as image:
                image.verify()
                for value in image.info.values():
                    if isinstance(value, str):
                        issues.extend(scan_secrets(path, value.encode('utf-8')))
        except (OSError, ValueError):
            issues.append({'file': path, 'rule': 'invalid_image'})
    return {'questions': count, 'assets': len(asset_paths), 'image_references': len(refs),
            'integrity': integrity, 'sha256': digest}, issues


def audit(root: Path) -> dict:
    actual_root = Path(git(root, 'rev-parse', '--show-toplevel').decode('utf-8').strip())
    if not os.path.samefile(root, actual_root):
        raise ValueError('Repository root is outside this project; do not stage the parent repository.')
    blobs, issues = read_index(root)
    manifest = 'scripts/release-manifest.json'
    if manifest not in blobs:
        raise ValueError('Missing staged source manifest.')
    config = json.loads(blobs[manifest])
    if set(config['source_directories']) != DIRECTORIES:
        raise ValueError('Source directories changed; review the public scope before updating this audit.')
    for path, content in blobs.items():
        rule = path_issue(path, config)
        if rule:
            issues.append({'file': path, 'rule': rule})
        if len(content) > 10*1024*1024:
            issues.append({'file': path, 'rule': 'unexpected_large_file'})
        issues.extend(scan_secrets(path, content))
    for missing in sorted(source_candidates(root, config)-blobs.keys()):
        issues.append({'file': missing, 'rule': 'source_omitted_from_index'})
    for folder in sorted(DIRECTORIES):
        if not any(path.startswith(folder+'/') for path in blobs):
            issues.append({'file': folder, 'rule': 'missing_source_directory'})
    seed, seed_issues = validate_seed(blobs, config)
    issues.extend(seed_issues)
    package = json.loads(blobs['package.json'])
    frontend = json.loads(blobs['frontend/package.json'])
    for path in ['package-lock.json', 'frontend/package-lock.json']:
        lock = json.loads(blobs[path])
        if lock['version'] != package['version'] or lock['packages']['']['version'] != package['version']:
            issues.append({'file': path, 'rule': 'version_mismatch'})
    if package['version'] != frontend['version']:
        issues.append({'file': 'frontend/package.json', 'rule': 'version_mismatch'})
    return {'passed': not issues, 'files': len(blobs), 'bytes': sum(map(len, blobs.values())),
            'seed': seed, 'issues': issues}


def main() -> int:
    try:
        report = audit(ROOT)
    except (ValueError, KeyError, OSError, sqlite3.Error, ImportError):
        # Malformed config/data may contain secrets: do not echo exception text.
        print(json.dumps({'passed': False, 'rule': 'audit_input_invalid',
                          'help': 'Check repository root, staged manifest, complete source, and development dependencies.'}))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
