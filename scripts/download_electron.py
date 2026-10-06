"""Fetch the official runtime and verify against the npm package's pinned hashes."""
import hashlib
import json
import subprocess
import zipfile
import time
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
root = Path(__file__).resolve().parents[1]
module = root / 'node_modules/electron'
version = json.loads((module / 'package.json').read_text('utf-8'))['version']
name = f'electron-v{version}-win32-x64.zip'
downloads = root / 'build/downloads'
downloads.mkdir(parents=True, exist_ok=True)
target = downloads / name
checksums = json.loads((module / 'checksums.json').read_text('utf-8'))
expected = checksums[name]
# curl does not read Windows Internet Settings. Honor the same configured
# environment/system proxy that Python and the desktop browser use, without
# embedding machine addresses or credentials in source or command output.
download_env = dict(os.environ)
for scheme, proxy in urllib.request.getproxies().items():
    if scheme in {'http', 'https', 'all'}:
        download_env[scheme + '_proxy'] = proxy
    elif scheme == 'no':
        download_env['no_proxy'] = proxy
def valid():
    return target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected
if not valid():
    url = f'https://github.com/electron/electron/releases/download/v{version}/{name}'
    def curl_output(command):
        for attempt in range(3):
            try:
                return subprocess.check_output(command, env=download_env)
            except subprocess.CalledProcessError:
                if attempt == 2:
                    raise RuntimeError('Official Electron download failed. Check HTTPS connectivity and your configured proxy.') from None
                time.sleep(attempt + 1)
    head = curl_output(['curl.exe', '-f', '-sS', '-I', '-L', '--max-time', '90', '-w', '\nURL:%{url_effective}', url]).decode()
    import re
    size = int(re.findall(r'(?im)^content-length:\s*(\d+)', head)[-1])
    direct_url = head.rsplit('URL:', 1)[1].strip()
    chunk_size = 8 * 1024 * 1024
    chunks = list(range(0, size, chunk_size))
    parts = downloads / f'parts-{version}'
    parts.mkdir(exist_ok=True)
    def download(start):
        end = min(start + chunk_size, size) - 1
        part = parts / str(start)
        have = part.stat().st_size if part.exists() else 0
        if have != end - start + 1:
            tail = parts / f'{start}.tail'
            curl_output(['curl.exe', '-f', '-sS', '-L', '--connect-timeout', '40', '--max-time', '900', '--range', f'{start+have}-{end}', '-o', str(tail), direct_url])
            if tail.stat().st_size != end - start + 1 - have:
                raise RuntimeError(f'Invalid resumed range: {start}')
            with part.open('ab') as output:
                output.write(tail.read_bytes())
            tail.unlink()
        if part.stat().st_size != end - start + 1:
            raise RuntimeError(f'Invalid range response: {start}')
        return start
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(download, start) for start in chunks]
        for index, future in enumerate(as_completed(futures), 1):
            future.result()
            print(f'Electron downloaded {index}/{len(chunks)} parts', flush=True)
    with target.open('wb') as output:
        for start in chunks:
            output.write((parts / str(start)).read_bytes())
    if not valid():
        raise RuntimeError('Electron runtime checksum mismatch')
with zipfile.ZipFile(target) as archive:
    archive.extractall(module / 'dist')
(module / 'path.txt').write_text('electron.exe', 'utf-8')
print('Electron verified and installed:', version)
