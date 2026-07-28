"""DOCX native and OOXML supplement behavior."""
from __future__ import annotations

import io
import zipfile

from app.platform.document_intelligence.providers.python_docx import (
    _extract_docx_ooxml_supplements,
    map_docx_output_to_ir,
)
from app.platform.document_intelligence.registry import ParserOutput
from app.platform.document_intelligence.source_artifact import SourceArtifact


def test_docx_ooxml_supplement_keeps_floating_alt_text_and_warns():
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("word/document.xml", """<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
          xmlns:wp='http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
          xmlns:m='http://schemas.openxmlformats.org/officeDocument/2006/math'>
          <w:body><w:p><w:r><w:drawing><wp:anchor><wp:docPr descr='Network architecture'/></wp:anchor></w:drawing></w:r></w:p>
          <m:oMath/></w:body></w:document>""")

    supplements, warnings = _extract_docx_ooxml_supplements(content.getvalue())

    assert supplements == [{
        "kind": "image_alt_text", "text": "Network architecture",
        "raw_locator": "word/document.xml#/w:body//w:drawing[1]/wp:docPr",
    }]
    assert any("FLOATING_DRAWING_REVIEW_REQUIRED" in warning for warning in warnings)
    assert any("OMML_FORMULA_REVIEW_REQUIRED" in warning for warning in warnings)


def test_docx_mapper_does_not_invent_page_for_ooxml_alt_text():
    source = SourceArtifact.from_bytes(b"docx", "source.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    output = ParserOutput(
        provider="python-docx", provider_version="1",
        pages=({
            "section_index": 1, "text_blocks": [],
            "ooxml_supplements": [{
                "kind": "image_alt_text", "text": "Architecture figure",
                "raw_locator": "word/document.xml#/w:body//w:drawing[1]/wp:docPr",
            }],
        },),
    )

    blocks, units, assets = map_docx_output_to_ir(output, source, "run", "parser")

    assert units == [] and assets == []
    assert blocks[0]["text"] == "Architecture figure"
    assert blocks[0].get("page_or_slide") is None
    assert blocks[0]["provenance"][0]["raw_locator"].startswith("word/document.xml#")
