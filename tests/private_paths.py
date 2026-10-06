"""Private materials are explicitly configurable, never bundled with source."""
import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def argument(name):
    try:return sys.argv[sys.argv.index(name)+1]
    except (ValueError,IndexError):return None
MATERIALS=Path(argument('--materials') or os.environ.get('QD_TEST_MATERIALS') or ROOT/'.local/test-materials').resolve()
DATA=Path(argument('--data') or os.environ['QD_TEST_DATA']).resolve() if argument('--data') or os.environ.get('QD_TEST_DATA') else None

OLD_APP=Path(argument('--old-app') or os.environ['QD_TEST_OLD_APP']).resolve() if argument('--old-app') or os.environ.get('QD_TEST_OLD_APP') else None
