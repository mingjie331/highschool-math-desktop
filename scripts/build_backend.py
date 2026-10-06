"""Build a portable backend, including DLLs when venv is based on Conda."""
import os
import sys
from pathlib import Path
from PyInstaller.__main__ import run

root=Path(__file__).resolve().parents[1]
os.chdir(root)
library=Path(sys.base_prefix)/'Library/bin'
extra=[]
if library.is_dir():
    os.environ['PATH']=str(library)+os.pathsep+os.environ.get('PATH','')
    for name in ['ffi.dll','libmpdec-4.dll','sqlite3.dll']:
        file=library/name
        if file.is_file():extra.extend(['--add-binary',str(file)+os.pathsep+'.'])
run(['--noconfirm','--clean','--name','question-backend','--onedir','--console',
     '--distpath','build/backend-runtime','--workpath','build/pyinstaller','--specpath','build','--paths','.',
     '--collect-all','uvicorn','--collect-all','pypdfium2','--collect-all','pypdfium2_raw','--hidden-import','backend.app',
     *extra,'backend/runner.py'])
