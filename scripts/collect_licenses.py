from pathlib import Path
import importlib.metadata
import shutil
import sys

root = Path(__file__).resolve().parents[1]
destination = root / 'resources/licenses'
destination.mkdir(parents=True, exist_ok=True)
for dist in importlib.metadata.distributions():
    for relative in dist.files or []:
        name = str(relative)
        if ('.dist-info/' in name or dist.metadata['Name'].lower()=='pypdfium2') and any(part.lower().startswith(('license', 'copying', 'copyright', 'notice')) for part in relative.parts):
            source = Path(dist.locate_file(relative))
            if source.is_file():
                target = destination / 'python' / dist.metadata['Name'] / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
for name in ['LICENSE.txt', 'LICENSE']:
    source = Path(sys.base_prefix) / name
    if source.is_file():
        shutil.copy2(source, destination / 'CPython-LICENSE.txt')
for package in ['react','react-dom','scheduler','lucide-react','pdfjs-dist']:
    source_dir = root / 'frontend/node_modules' / package
    for source in source_dir.iterdir():
        if source.is_file() and source.name.lower().startswith(('license','notice','copying','copyright')):
            target = destination / 'frontend' / package / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source,target)
print('Third-party license files collected.')

# A venv built on Conda can need libffi/mpdecimal DLLs from its base runtime.
package_cache=Path(sys.base_prefix)/'pkgs'
if package_cache.is_dir():
    for prefix in ['libffi-','mpdecimal-','sqlite-']:
        for package in package_cache.glob(prefix+'*'):
            if not package.is_dir():continue
            for source in (package/'info/licenses').rglob('*'):
                if source.is_file():
                    target=destination/'native'/package.name/source.relative_to(package/'info/licenses')
                    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
