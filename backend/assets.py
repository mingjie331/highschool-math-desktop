"""One resource contract for formal questions, unfinished drafts and rendering."""
from pathlib import Path, PureWindowsPath
import io
import re
import threading
from typing import Any

IMAGE_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
ASSET_LOCK = threading.RLock()


def validate_upload(content: bytes, suffix: str) -> None:
    """Validate bytes before making a resource visible to questions/drafts."""
    if not content:
        raise ValueError('上传文件为空')
    if suffix in {'.png', '.jpg', '.jpeg'}:
        from PIL import Image, UnidentifiedImageError
        try:
            with Image.open(io.BytesIO(content)) as image:
                expected = 'PNG' if suffix == '.png' else 'JPEG'
                if image.format != expected:
                    raise ValueError('文件实际格式与扩展名不一致')
                if image.width * image.height > 50_000_000:
                    raise ValueError('图片不能超过 5000 万像素')
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                image.load()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError('图片损坏或无法解码，请重新导出图片') from exc
    elif suffix == '.pdf':
        from pypdf import PdfReader
        from pypdf.generic import ArrayObject, StreamObject
        try:
            if not content.startswith(b'%PDF-') or not re.search(rb'%%EOF\s*$', content[-1024:]):
                raise ValueError('PDF 文件不完整')
            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise ValueError('配图 PDF 不能加密或设置密码')
            if not 1 <= len(reader.pages) <= 200:
                raise ValueError('配图 PDF 须包含 1 至 200 页')
            for page in reader.pages:
                if float(page.mediabox.width) <= 0 or float(page.mediabox.height) <= 0:
                    raise ValueError('PDF 页面尺寸无效')
                contents = page.get('/Contents')
                if contents is not None:
                    resolved = contents.get_object()
                    streams = resolved if isinstance(resolved, ArrayObject) else [resolved]
                    if any(not isinstance(item.get_object(), StreamObject) for item in streams):
                        raise ValueError('PDF 页面内容结构无效')
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('PDF 损坏或无法读取，请重新导出 PDF') from exc
    else:
        raise ValueError('只允许上传 PNG、JPG、JPEG 或 PDF')


def image_references(question: dict[str, Any]) -> set[str]:
    fields = [question.get(key, '') for key in ('question_tex', 'answer_tex', 'solution_tex')]
    fields.extend(question.get('options', []))
    return {name.replace('\\', '/').strip() for name in IMAGE_RE.findall('\n'.join(fields))}


def asset_path(root: Path, relative: str, *, require_file: bool = True) -> Path:
    relative = relative.replace('\\', '/').strip()
    rel = Path(relative)
    candidate = (root / rel).resolve()
    if (rel.is_absolute() or PureWindowsPath(relative).drive or '..' in rel.parts
            or ':' in relative or not candidate.is_relative_to((root / 'assets').resolve())
            or (require_file and not candidate.is_file())):
        raise ValueError(f'配图不存在或路径不安全：{relative}')
    return candidate
