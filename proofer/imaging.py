"""Accept a JPG/PNG as artwork alongside PDFs, by wrapping it into a proper single-page PDF first.

A bare image has no PDF structure at all (no page tree, no /Resources, no OCGs), and several checks
(layers, spot colours, embedded-font enumeration, page insertion during registration) assume that
structure exists and crash outright on an image opened directly with pymupdf. Converting to a real
one-page PDF up front - the image placed as a normal image object on a normal page - means every
check downstream sees an ordinary PDF and just takes the same "image-only artwork" path a flattened
scan already takes (no text layer, so text/spelling/copy-deck checks fall back to visual + OCR).
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"


def is_pdf(data: bytes) -> bool:
    return data.lstrip()[:5] == b"%PDF-"


def is_image(data: bytes) -> bool:
    return data.startswith(_PNG) or data.startswith(_JPEG)


def to_pdf_bytes(data: bytes) -> bytes:
    """A JPG/PNG's bytes as a real single-page PDF."""
    with pymupdf.open(stream=data, filetype="png" if data.startswith(_PNG) else "jpeg") as doc:
        return doc.convert_to_pdf()


def open_pdf(path: str) -> pymupdf.Document:
    """Open a file that may be a PDF or a bare JPG/PNG, always as a genuine PDF document."""
    data = Path(path).read_bytes()
    if not is_pdf(data) and is_image(data):
        data = to_pdf_bytes(data)
    return pymupdf.open(stream=data, filetype="pdf")
