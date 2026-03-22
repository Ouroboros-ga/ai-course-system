from pathlib import Path

XLSX_FILE = "tst.xlsx"
DOCX_FILE = "tst.docx"
PDF_FILE = "tst.pdf"

ASSETS_PATH = Path(__file__).parent.parent / "assets"
XLSX_PATH = ASSETS_PATH / XLSX_FILE
DOCX_PATH = ASSETS_PATH / DOCX_FILE
PDF_PATH = ASSETS_PATH / PDF_FILE
