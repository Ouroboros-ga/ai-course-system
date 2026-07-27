"""PaddleOCR provider wrapping the ``paddleocr`` Python package.

Runs **inside** the standalone PaddleOCR service container (its own virtualenv
with paddleocr/paddlepaddle installed). The main backend NEVER imports this
module -- it talks to the service over HTTP via ``PaddleOcrHttpAdapter``.

Honest degradation: if paddleocr/paddlepaddle is not importable, every call
raises so the HTTP endpoint returns a structured error; we never fabricate
OCR output.
"""
from __future__ import annotations

import hashlib
import io
import logging
from typing import List, Optional

from schemas import OcrBlock, OcrPage

logger = logging.getLogger("paddleocr-provider")


# Lazily imported so the service can still start (and /health can report
# unavailable) even if paddleocr is not yet installed -- useful during dev.
class _PaddleRuntime:
    def __init__(self) -> None:
        self._available = False
        self._engine = None
        self.version = "unavailable"
        self.model_hash = "unavailable"
        self.uses_gpu = False
        try:
            import paddleocr  # type: ignore  # noqa: F401
            from paddleocr import PaddleOCR  # type: ignore
            self._engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
            self._available = True
            self.version = f"paddleocr-{getattr(paddleocr, '__version__', 'unknown')}"
            try:
                import paddle  # type: ignore
                self.uses_gpu = bool(paddle.is_compiled_with_cuda())
            except Exception:
                self.uses_gpu = False
            self.model_hash = self._compute_model_hash()
            logger.info("PaddleOCR ready: %s gpu=%s", self.version, self.uses_gpu)
        except Exception:
            logger.exception("PaddleOCR not available; service will report unhealthy")

    def _compute_model_hash(self) -> str:
        # PaddleOCR 下载的检测/识别模型在 ~/.paddleocr 下；这里只取一个稳定摘要用于审计。
        import os
        import glob
        home = os.path.expanduser("~/.paddleocr")
        h = hashlib.sha256()
        files = sorted(glob.glob(os.path.join(home, "**", "*.pdmodel"), recursive=True)) \
                + sorted(glob.glob(os.path.join(home, "**", "*.pdiparams"), recursive=True))
        for f in files[:8]:
            try:
                with open(f, "rb") as fh:
                    h.update(fh.read(65536))
                    h.update(f.encode())
            except Exception:
                pass
        return h.hexdigest()[:16] if files else "no-model-files"

    @property
    def available(self) -> bool:
        return self._available

    def ocr_image(self, image_bytes: bytes, lang: str = "ch") -> List[OcrBlock]:
        if not self._available:
            raise RuntimeError("PaddleOCR runtime not available")
        from PIL import Image  # type: ignore
        img = Image.open(io.BytesIO(image_bytes))
        result = self._engine.ocr(img, cls=True)
        return self._normalize(result, img.width, img.height)

    def ocr_pdf(self, pdf_bytes: bytes, lang: str = "ch",
                pages: Optional[List[int]] = None, max_pages: int = 50) -> List[OcrPage]:
        import tempfile, os
        if not self._available:
            raise RuntimeError("PaddleOCR runtime not available")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            tf.write(pdf_bytes)
            tmp_path = tf.name
        try:
            # PaddleOCR.ocr 支持 pdf 输入；pages 参数限制页范围
            kw = {"cls": True}
            target_pages = pages if pages else None
            if target_pages is not None:
                target_pages = target_pages[:max_pages]
            raw = self._engine.ocr(tmp_path, cls=True)
            out: List[OcrPage] = []
            # raw 是按页的列表；每页是 [(box, (text, conf)), ...]
            for page_idx, page_result in enumerate(raw or [], start=1):
                if target_pages is not None and page_idx not in target_pages:
                    continue
                if page_idx > max_pages:
                    break
                out.append(OcrPage(page=page_idx, blocks=self._normalize_page(page_result)))
            return out
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    @staticmethod
    def _normalize(page_result, width: float, height: float) -> List[OcrBlock]:
        page = OcrPage(page=1, blocks=[])
        return PaddleRuntime._normalize_page(page_result)

    @staticmethod
    def _normalize_page(page_result) -> List[OcrBlock]:
        blocks: List[OcrBlock] = []
        if not page_result:
            return blocks
        for entry in page_result:
            # entry: [box([[x,y],...x4]), (text, conf)]
            try:
                box = entry[0]
                text, conf = entry[1]
                xs = [pt[0] for pt in box]
                ys = [pt[1] for pt in box]
                blocks.append(OcrBlock(
                    text=text,
                    bbox=[min(xs), min(ys), max(xs), max(ys)],
                    confidence=float(conf),
                    kind="text",
                ))
            except Exception:
                continue
        return blocks


# Module-level singleton; imported by app.py
PaddleRuntime = _PaddleRuntime()
