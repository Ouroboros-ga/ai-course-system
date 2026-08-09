#!/usr/bin/env bash
set -euo pipefail

readonly app_root="/opt/smartcarb-git"
readonly app_python="${app_root}/backend/.venv/bin/python"
temporary_dir="$(mktemp -d /tmp/smartcarb-document-smoke.XXXXXX)"
trap 'rm -rf -- "${temporary_dir}"' EXIT

"${app_python}" - "${temporary_dir}" <<'PY'
from pathlib import Path
import sys

from docx import Document
from pptx import Presentation

root = Path(sys.argv[1])
document = Document()
document.add_heading("课程材料解析烟测", level=1)
document.add_paragraph("Synthetic document smoke test 123")
document.save(root / "smoke-document.docx")

presentation = Presentation()
slide = presentation.slides.add_slide(presentation.slide_layouts[1])
slide.shapes.title.text = "课程材料解析烟测"
slide.placeholders[1].text = "Synthetic presentation smoke test 123"
presentation.save(root / "smoke-presentation.pptx")
PY

libreoffice --headless --convert-to pdf --outdir "${temporary_dir}" \
  "${temporary_dir}/smoke-document.docx" \
  "${temporary_dir}/smoke-presentation.pptx" >/dev/null

test -s "${temporary_dir}/smoke-document.pdf"
test -s "${temporary_dir}/smoke-presentation.pdf"

pdfinfo "${temporary_dir}/smoke-document.pdf" >/dev/null
pdfinfo "${temporary_dir}/smoke-presentation.pdf" >/dev/null
pdftoppm -f 1 -singlefile -png "${temporary_dir}/smoke-document.pdf" \
  "${temporary_dir}/smoke-docx-page" >/dev/null 2>&1
test -s "${temporary_dir}/smoke-docx-page.png"

echo "LibreOffice and Poppler document smoke passed"
