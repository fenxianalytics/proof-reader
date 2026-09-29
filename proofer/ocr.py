"""Optional OCR, used only to *describe* a region the pixel check already flagged.

OCR never decides that two files match. A real OCR engine (not a language model) is used on purpose:
it reads what is drawn and doesn't autocorrect "0.5 mg" into "5 mg". If the engine isn't installed the
proofer still runs; the report just says OCR was unavailable.

Side text on cartons runs vertically, so a crop that is taller than it is wide is also read turned 90° each
way, and whichever orientation the engine is most confident about wins.
"""
from __future__ import annotations

import re
import threading

import cv2
import numpy as np

_engine = None
_tried = False
_lock = threading.Lock()  # the web app runs proofs on worker threads; keep one inference at a time


def available() -> bool:
    return _get() is not None


def _get():
    global _engine, _tried
    if not _tried:
        _tried = True
        try:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
        except Exception:
            _engine = None
    return _engine


def lines(img_rgb: np.ndarray, min_conf: float = 0.5) -> list[tuple]:
    """[(box 4x2 in img coords, text, confidence)] for one image, upright orientation only."""
    eng = _get()
    if eng is None or img_rgb.size == 0:
        return []
    try:
        with _lock:
            res, _ = eng(cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR))
    except Exception:
        return []
    return [(np.array(b, np.float32), t, float(c)) for b, t, c in (res or []) if float(c) >= min_conf and t.strip()]


def _read_one(img_rgb: np.ndarray, min_conf: float) -> tuple[str, float]:
    items = lines(img_rgb, min_conf)
    if not items:
        return "", 0.0
    items = [(float(b[:, 1].min()), float(b[:, 0].min()), t, c) for b, t, c in items]
    items.sort(key=lambda t: (round(t[0] / 12), t[1]))
    txt = re.sub(r"\s+", " ", " ".join(t[2] for t in items)).strip()
    return txt, sum(c * len(t) for _, _, t, c in items)


def read(img_rgb: np.ndarray, min_conf: float = 0.5) -> str:
    """Text found in a crop, reading order top-to-bottom / left-to-right, low-confidence words dropped."""
    if _get() is None or img_rgb.size == 0 or min(img_rgb.shape[:2]) < 6:
        return ""
    h, w = img_rgb.shape[:2]
    scale = 2.0 if max(h, w) < 400 else 1.0  # tiny crops OCR far better upscaled
    if scale != 1.0:
        img_rgb = cv2.resize(img_rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
    img_rgb = cv2.copyMakeBorder(img_rgb, 12, 12, 12, 12, cv2.BORDER_REPLICATE)
    best = _read_one(img_rgb, min_conf)
    if h > 1.6 * w:  # probably vertical text: try it turned both ways
        for rot in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):
            cand = _read_one(cv2.rotate(img_rgb, rot), min_conf)
            if cand[1] > best[1] * 1.15:
                best = cand
    return best[0]


def page_lines(img_rgb: np.ndarray, min_conf: float = 0.5, vertical: bool = False) -> list[tuple]:
    """All text lines on a page image, including vertical ones. One upright pass over the page; then only the tall,
    narrow ink regions it didn't read (side panels, rotated lot lines) are cut out and read turned 90° each way.
    Returns [(box 4x2 in page-image coords, text, confidence, angle)], angle 0 / 90 / 270."""
    # an "upright" line that is taller than it is wide is sideways text misread: leave it to the rotated reader
    up = [(b, t, c, 0) for b, t, c in lines(img_rgb, min_conf)
          if (b[:, 1].max() - b[:, 1].min()) < 1.5 * (b[:, 0].max() - b[:, 0].min())]
    if not vertical:  # the sideways page pass is slow; flagged regions are still read sideways by read()
        return up
    H, W = img_rgb.shape[:2]
    ink = (cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY) < 150).astype(np.uint8)
    for b, *_ in up:  # blank out what the upright pass already read
        x0, y0, x1, y1 = (int(v) for v in (b[:, 0].min() - 3, b[:, 1].min() - 3, b[:, 0].max() + 3, b[:, 1].max() + 3))
        ink[max(0, y0):y1, max(0, x0):x1] = 0
    # characters of a vertical line sit on top of each other: join them vertically, not sideways
    grow = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_RECT, (3, max(9, H // 150))))
    n, _lab, stats, _ = cv2.connectedComponentsWithStats(grow, connectivity=8)
    out = list(up)
    cands = []
    for i in range(1, n):
        x, y, w, h = (int(stats[i, c]) for c in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        if h < 3 * w or h < 40 or w < 12 or w > 0.2 * W:
            continue
        fill = float(ink[y:y + h, x:x + w].mean())
        if fill > 0.45 or fill < 0.04:
            continue  # solid (barcode bars, rules) or nearly empty - not a line of text
        cands.append((h, x, y, w))
    for h, x, y, w in sorted(cands, reverse=True)[:12]:
        pad = max(4, w // 3)
        x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + h + pad)
        crop = img_rgb[y0:y1, x0:x1]
        best = None
        for code, ang in ((cv2.ROTATE_90_CLOCKWISE, 90), (cv2.ROTATE_90_COUNTERCLOCKWISE, 270)):
            txt, score = _read_one(cv2.rotate(crop, code), max(min_conf, 0.6))
            if txt and (best is None or score > best[1]):
                best = (txt, score, ang)
        if best and len(best[0]) >= 3:
            box = np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
            out.append((box, best[0], min(1.0, best[1] / max(1, len(best[0]))), best[2]))
    return out
