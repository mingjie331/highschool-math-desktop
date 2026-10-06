"""Create a self-contained version privately, then publish it atomically."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

from .assets import asset_path


def resource_hashes(assets: dict[str, bytes], preamble: bytes):
    return {
        'assets': {name: hashlib.sha256(content).hexdigest() for name, content in assets.items()},
        'template_sha256': hashlib.sha256(preamble).hexdigest(),
    }


@contextmanager
def staged_archive(destination: Path, assets: dict[str, bytes], preamble: bytes):
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.building-', dir=destination.parent))
    try:
        (stage/'preamble.tex').write_bytes(preamble)
        for name, content in assets.items():
            file = asset_path(stage, name, require_file=False)
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content)
        yield stage
        os.replace(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
