import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, Optional

import fitz

from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LIBREOFFICE_PATHS = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    "/usr/bin/libreoffice",
    "/usr/bin/soffice",
    "/usr/local/bin/libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]


def _find_libreoffice() -> Optional[str]:
    for path in LIBREOFFICE_PATHS:
        if Path(path).exists():
            return path
    env_path = os.environ.get("LIBREOFFICE_PATH")
    if env_path and Path(env_path).exists():
        return env_path
    return None


def convert_office_to_pdf(input_path: str, output_dir: Optional[str] = None) -> Optional[str]:
    soffice = _find_libreoffice()
    if not soffice:
        logger.error("LibreOffice not found. Cannot convert office document to PDF.")
        return None

    input_file = Path(input_path)
    if not input_file.exists():
        logger.error(f"Input file not found: {input_path}")
        return None

    if output_dir is None:
        output_dir = str(input_file.parent)

    # LibreOffice locks its user profile.  A profile per conversion prevents
    # parallel parse/media workers from making each other fail without stderr.
    with tempfile.TemporaryDirectory(prefix="ai_course_libreoffice_profile_") as profile_dir:
        user_profile_uri = Path(profile_dir).resolve().as_uri()
        cmd = [
            soffice,
            "--headless",
            f"-env:UserInstallation={user_profile_uri}",
            "--convert-to", "pdf",
            "--outdir", output_dir,
            str(input_file),
        ]

        logger.info(f"Converting {input_file.name} to PDF: {' '.join(cmd)}")

        try:
            kwargs = {
                "capture_output": True,
                "timeout": 300,
            }

            if os.name == "nt":
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = subprocess.SW_HIDE
                kwargs["startupinfo"] = si

            result = subprocess.run(cmd, **kwargs)

            stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
            stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

            if result.returncode != 0:
                logger.error(f"LibreOffice conversion failed: {stderr}")
                return None

            pdf_filename = input_file.stem + ".pdf"
            pdf_path = Path(output_dir) / pdf_filename

            if pdf_path.exists():
                logger.info(f"PDF created: {pdf_path}")
                return str(pdf_path)
            else:
                logger.error(f"PDF file not found after conversion: {pdf_path}")
                return None

        except subprocess.TimeoutExpired:
            logger.error("LibreOffice conversion timed out (300s)")
            return None
        except Exception as e:
            logger.error(f"LibreOffice conversion error: {e}")
            return None


async def convert_office_to_pdf_async(input_path: str, output_dir: Optional[str] = None) -> Optional[str]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, convert_office_to_pdf, input_path, output_dir)


def render_pdf_to_images(
    pdf_path: str,
    output_dir: str,
    dpi: int = 150,
    image_format: str = "png",
    pages: Optional[Iterable[int]] = None,
) -> list[str]:
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        logger.error(f"PDF file not found: {pdf_path}")
        return []

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    image_paths = []

    try:
        doc = fitz.open(str(pdf_file))
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)

        selected_pages = None
        if pages is not None:
            selected_pages = {
                int(page)
                for page in pages
                if isinstance(page, int) or (isinstance(page, str) and page.isdigit())
            }
        for page_num in range(len(doc)):
            page_number = page_num + 1
            if selected_pages is not None and page_number not in selected_pages:
                continue
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=mat)

            img_filename = f"slide_{page_number}.{image_format}"
            img_path = output_path / img_filename
            pix.save(str(img_path))
            image_paths.append(str(img_path))

        doc.close()
        logger.info(f"Rendered {len(image_paths)} pages from {pdf_file.name} at {dpi} DPI")

    except Exception as e:
        logger.error(f"PDF rendering error: {e}")
        return []

    return image_paths


def is_office_file(file_path: str) -> bool:
    ext = Path(file_path).suffix.lower()
    return ext in (".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls")


def is_pdf_file(file_path: str) -> bool:
    ext = Path(file_path).suffix.lower()
    return ext == ".pdf"


def get_or_create_pdf(source_path: str, cache_dir: Optional[str] = None) -> Optional[str]:
    if is_pdf_file(source_path):
        return source_path

    if not is_office_file(source_path):
        logger.warning(f"Unsupported file type for PDF conversion: {source_path}")
        return None

    if cache_dir is None:
        cache_dir = str(Path(tempfile.gettempdir()) / "ai_course_pdf_cache")

    Path(cache_dir).mkdir(parents=True, exist_ok=True)

    source_file = Path(source_path)
    pdf_filename = source_file.stem + ".pdf"
    pdf_path = Path(cache_dir) / pdf_filename

    if pdf_path.exists():
        try:
            source_mtime = source_file.stat().st_mtime
            pdf_mtime = pdf_path.stat().st_mtime
            if pdf_mtime >= source_mtime:
                logger.info(f"Using cached PDF: {pdf_path}")
                return str(pdf_path)
        except OSError:
            pass

    result = convert_office_to_pdf(source_path, cache_dir)
    return result


def get_or_render_slides(
    source_path: str,
    course_id: int,
    slides_dir: str,
    dpi: int = 150,
) -> list[dict]:
    pdf_path = get_or_create_pdf(source_path)
    if not pdf_path:
        logger.warning(f"Cannot get PDF for source: {source_path}, falling back to text rendering")
        return []

    course_slide_dir = Path(slides_dir) / str(course_id)
    course_slide_dir.mkdir(parents=True, exist_ok=True)

    image_paths = render_pdf_to_images(pdf_path, str(course_slide_dir), dpi=dpi)

    slides_info = []
    for i, img_path in enumerate(image_paths):
        slides_info.append({
            "page": i + 1,
            "url": f"/api/v1/document/course/{course_id}/slide/{i + 1}",
        })

    return slides_info
