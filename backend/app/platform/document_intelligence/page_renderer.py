"""Selective, page-aware rendering for OCR enrichment."""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class RenderedPage:
    unit_index: int
    image_bytes: bytes
    width: int
    height: int
    rendition_artifact_id: str


class PdfiumPageRenderer:
    """Render only requested PDF pages without re-parsing document semantics."""

    def render(self, pdf_bytes: bytes, unit_indices: Sequence[int], *, dpi: int = 180) -> list[RenderedPage]:
        if dpi < 72 or dpi > 300:
            raise ValueError("dpi must be between 72 and 300")
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:
            raise RuntimeError("pypdfium2 is required for selective PDF OCR rendering") from exc
        document = pdfium.PdfDocument(pdf_bytes)
        requested = sorted(set(int(page) for page in unit_indices if int(page) >= 1))
        result: list[RenderedPage] = []
        try:
            for page_number in requested:
                if page_number > len(document):
                    continue
                page = document[page_number - 1]
                bitmap = page.render(scale=dpi / 72.0)
                image = bitmap.to_pil()
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                result.append(RenderedPage(
                    unit_index=page_number,
                    image_bytes=buffer.getvalue(),
                    width=image.width,
                    height=image.height,
                    rendition_artifact_id=f"pdfium:{page_number}:{dpi}",
                ))
        finally:
            document.close()
        return result
