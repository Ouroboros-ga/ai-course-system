#!/usr/bin/env python3
"""Run a PaddleOCR HTTP smoke test with generated, non-user test data."""

from __future__ import annotations

import argparse
import base64
import io
import json
import urllib.request


GLYPHS = {
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "S": ("11111", "10000", "10000", "11111", "00001", "00001", "11111"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("11110", "00001", "00001", "11110", "10000", "10000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
}


def make_pgm(text: str = "TEST123", scale: int = 10) -> bytes:
    width = (len(text) * 6 - 1) * scale
    height = 7 * scale
    pixels = bytearray([255]) * (width * height)
    for char_index, char in enumerate(text):
        glyph = GLYPHS[char]
        for row_index, row in enumerate(glyph):
            for column_index, bit in enumerate(row):
                if bit != "1":
                    continue
                x0 = (char_index * 6 + column_index) * scale
                y0 = row_index * scale
                for y in range(y0, y0 + scale):
                    start = y * width + x0
                    pixels[start : start + scale] = b"\x00" * scale
    return f"P5\n{width} {height}\n255\n".encode() + pixels


def make_image() -> bytes:
    """Prefer a normal rendered PNG; retain a stdlib-only PGM fallback."""
    try:
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (1000, 240), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 96
        )
        draw.text((40, 50), "课程材料 TEST 123", fill="black", font=font)
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    except (ImportError, OSError):
        return make_pgm()


def make_pdf(image_bytes: bytes) -> bytes:
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    output = io.BytesIO()
    image.save(output, format="PDF", resolution=150)
    return output.getvalue()


def post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8090/v1/ocr")
    parser.add_argument(
        "--pdf-url", default="http://127.0.0.1:8090/v1/ocr/pdf"
    )
    args = parser.parse_args()
    image_bytes = make_image()
    result = post_json(
        args.url,
        {"image_b64": base64.b64encode(image_bytes).decode(), "lang": "ch"},
    )
    pages = result.get("pages", [])
    blocks = pages[0].get("blocks", []) if pages else []
    pdf_result = post_json(
        args.pdf_url,
        {
            "pdf_b64": base64.b64encode(make_pdf(image_bytes)).decode(),
            "lang": "ch",
            "max_pages": 1,
        },
    )
    pdf_pages = pdf_result.get("pages", [])
    pdf_blocks = pdf_pages[0].get("blocks", []) if pdf_pages else []
    print(
        json.dumps(
            {
                "success": True,
                "provider_version": result.get("provider_version"),
                "image_block_count": len(blocks),
                "image_texts": [block.get("text", "") for block in blocks],
                "pdf_block_count": len(pdf_blocks),
                "pdf_texts": [block.get("text", "") for block in pdf_blocks],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
