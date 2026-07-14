"""Tests for DocumentProbe and ProbeResult."""

import pytest

from app.platform.document_intelligence.probe import (
    DetectedFormat,
    DocumentProbe,
    EncryptionStatus,
    ProbeResult,
)


class TestProbeResult:
    """ProbeResult basic behavior."""

    def test_is_parseable_returns_true_for_known_formats(self) -> None:
        pr = ProbeResult(detected_format=DetectedFormat.PPTX)
        assert pr.is_parseable() is True
        pr2 = ProbeResult(detected_format=DetectedFormat.PDF)
        assert pr2.is_parseable() is True

    def test_is_parseable_returns_false_for_unparseable(self) -> None:
        for fmt in (DetectedFormat.UNSUPPORTED, DetectedFormat.CORRUPT,
                    DetectedFormat.ENCRYPTED):
            pr = ProbeResult(detected_format=fmt)
            assert pr.is_parseable() is False

    def test_needs_ocr_true_when_low_text_and_image_pages(self) -> None:
        pr = ProbeResult(
            detected_format=DetectedFormat.PPTX,
            estimated_text_coverage=0.2,
            image_only_pages=(1, 2, 3),
        )
        assert pr.needs_ocr() is True

    def test_needs_ocr_false_when_good_text_coverage(self) -> None:
        pr = ProbeResult(
            detected_format=DetectedFormat.PPTX,
            estimated_text_coverage=0.8,
            image_only_pages=(),
        )
        assert pr.needs_ocr() is False


class TestDocumentProbe:
    """DocumentProbe format detection and probing."""

    @pytest.fixture
    def probe(self) -> DocumentProbe:
        return DocumentProbe()

    def test_detect_pptx_by_magic_bytes(self, probe: DocumentProbe) -> None:
        # Minimal valid ZIP header for PPTX-like content (needs >= 30 bytes)
        data = (
            b"\x50\x4b\x03\x04"  # ZIP magic
            + b"\x14\x00"        # version needed
            + b"\x00\x00"        # general purpose flag (no encryption)
            + b"\x00\x00"        # compression method
            + b"\x00" * 22       # pad to >= 30 bytes
        )
        result = probe.probe(data, filename="test.pptx",
                             mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")
        assert result.detected_format == DetectedFormat.PPTX

    def test_detect_pdf_by_magic_bytes(self, probe: DocumentProbe) -> None:
        data = b"%PDF-1.4 some pdf content here"
        result = probe.probe(data, filename="test.pdf", mime="application/pdf")
        assert result.detected_format == DetectedFormat.PDF

    def test_detect_image_png(self, probe: DocumentProbe) -> None:
        data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"rest_of_png_data"
        result = probe.probe(data, filename="test.png", mime="image/png")
        assert result.detected_format == DetectedFormat.IMAGE

    def test_detect_image_jpeg(self, probe: DocumentProbe) -> None:
        data = b"\xff\xd8\xff\xe0" + b"jpeg_data"
        result = probe.probe(data, filename="test.jpg", mime="image/jpeg")
        assert result.detected_format == DetectedFormat.IMAGE

    def test_corrupt_empty_data(self, probe: DocumentProbe) -> None:
        result = probe.probe(b"")
        assert result.detected_format == DetectedFormat.CORRUPT

    def test_unsupported_format(self, probe: DocumentProbe) -> None:
        data = b"\x00\x01\x02\x03unknown_format_data"
        result = probe.probe(data, filename="test.xyz", mime="application/octet-stream")
        assert result.detected_format == DetectedFormat.UNSUPPORTED

    def test_probe_includes_file_size(self, probe: DocumentProbe) -> None:
        data = b"test data for probe size check" * 100
        result = probe.probe(data, filename="test.pdf", mime="application/pdf")
        assert result.file_size_bytes == len(data)

    def test_probe_includes_duration(self, probe: DocumentProbe) -> None:
        data = b"%PDF-1.4 some content"
        result = probe.probe(data, filename="test.pdf", mime="application/pdf")
        assert result.probe_duration_ms > 0

    def test_image_probe_adds_warning(self, probe: DocumentProbe) -> None:
        data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"image_data"
        result = probe.probe(data, filename="test.png", mime="image/png")
        assert len(result.warnings) > 0
        assert "OCR" in result.warnings[0]

    def test_detect_format_via_mime_presentation(self, probe: DocumentProbe) -> None:
        data = b"\x50\x4b\x03\x04" + b"\x00" * 30
        result = probe.probe(
            data,
            filename="slides.pptx",
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        assert result.detected_format == DetectedFormat.PPTX

    def test_detect_format_via_mime_word(self, probe: DocumentProbe) -> None:
        data = b"\x50\x4b\x03\x04" + b"\x00" * 30
        result = probe.probe(
            data,
            filename="report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert result.detected_format == DetectedFormat.DOCX
