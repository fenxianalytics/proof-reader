"""Render synthetic pack designs to PDF.

A design is a plain dict, so a defect is just an edit to that dict followed by a re-render.
Everything here is fictional; nothing is a real product.
"""
from __future__ import annotations

import math
import warnings
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import zxingcpp

warnings.filterwarnings("ignore", category=DeprecationWarning)

MM = 72 / 25.4
FONT_DIR = Path("C:/Windows/Fonts")
FONT_FILES = {"arial": "arial.ttf", "arialbd": "arialbd.ttf", "ariali": "ariali.ttf",
              "times": "times.ttf", "timesbd": "timesbd.ttf", "cour": "cour.ttf"}
WHITE, BLACK, GREY = (255, 255, 255), (0, 0, 0), (110, 110, 110)

_FONTS: dict[str, pymupdf.Font] = {}


def font(name: str) -> pymupdf.Font:
    if name not in _FONTS:
        _FONTS[name] = pymupdf.Font(fontfile=str(FONT_DIR / FONT_FILES[name]))
    return _FONTS[name]


# ── barcodes ──────────────────────────────────────────────────────────────
_L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"]
_G = ["0100111", "0110011", "0011011", "0100001", "0011101", "0111001", "0000101", "0010001", "0001001", "0010111"]
_R = ["1110010", "1100110", "1101100", "1000010", "1011100", "1001110", "1010000", "1000100", "1001000", "1110100"]
_PAR = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]
_ZXFMT = {"code128": zxingcpp.BarcodeFormat.Code128, "datamatrix": zxingcpp.BarcodeFormat.DataMatrix,
          "qr": zxingcpp.BarcodeFormat.QRCode}


def ean13_check(d12: str) -> str:
    return str((10 - sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d12)) % 10) % 10)


def ean13_modules(d13: str) -> str:
    par = _PAR[int(d13[0])]
    m = "101" + "".join((_L if par[i] == "L" else _G)[int(c)] for i, c in enumerate(d13[1:7])) + "01010"
    return m + "".join(_R[int(c)] for c in d13[7:]) + "101"


_ZX_CACHE: dict = {}


def zx_modules(fmt: str, value: str):
    """('1d', '1010..') for linear codes, ('2d', 2-D bool array) for matrix codes."""
    key = (fmt, value)
    if key not in _ZX_CACHE:
        arr = np.array(zxingcpp.write_barcode(_ZXFMT[fmt], value), copy=True)
        dark = arr < 128
        ys, xs = np.where(dark)
        if fmt == "code128":
            row = dark[arr.shape[0] // 2]
            xs = np.where(row)[0]
            _ZX_CACHE[key] = ("1d", "".join("1" if v else "0" for v in row[xs.min(): xs.max() + 1]))
        else:
            _ZX_CACHE[key] = ("2d", dark[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1])
    return _ZX_CACHE[key]


def barcode_size(el) -> tuple[float, float]:
    """(along-bars width, bar height) in points, before rotation."""
    if el["fmt"] == "ean13":
        return 95 * el["mw"], el["h"]
    kind, m = zx_modules(el["fmt"], el["value"])
    if kind == "1d":
        return len(m) * el["mw"], el["h"]
    return m.shape[1] * el["mw"], m.shape[0] * el["mw"]


# ── braille (English grade 1) ─────────────────────────────────────────────
_BRL = {"a": (1,), "b": (1, 2), "c": (1, 4), "d": (1, 4, 5), "e": (1, 5), "f": (1, 2, 4), "g": (1, 2, 4, 5), "h": (1, 2, 5),
        "i": (2, 4), "j": (2, 4, 5), "k": (1, 3), "l": (1, 2, 3), "m": (1, 3, 4), "n": (1, 3, 4, 5), "o": (1, 3, 5),
        "p": (1, 2, 3, 4), "q": (1, 2, 3, 4, 5), "r": (1, 2, 3, 5), "s": (2, 3, 4), "t": (2, 3, 4, 5), "u": (1, 3, 6),
        "v": (1, 2, 3, 6), "w": (2, 4, 5, 6), "x": (1, 3, 4, 6), "y": (1, 3, 4, 5, 6), "z": (1, 3, 5, 6)}
_DOT_POS = {1: (0, 0), 2: (0, 1), 3: (0, 2), 4: (1, 0), 5: (1, 1), 6: (1, 2)}


def braille_cells(text: str) -> list[tuple]:
    out, num = [], False
    for ch in text.lower():
        if ch.isdigit():
            if not num:
                out.append((3, 4, 5, 6)); num = True
            out.append(_BRL["jabcdefghi"[int(ch)]])
        elif ch in _BRL:
            out.append(_BRL[ch]); num = False
        else:
            out.append(()); num = False
    return out


# ── images ────────────────────────────────────────────────────────────────
def make_image(seed: int, px_w: int, px_h: int) -> bytes:
    """Deterministic illustration; the same seed always shows the same picture at any pixel size."""
    rng = np.random.RandomState(seed)
    W, H = 600, int(600 * px_h / px_w)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    base = np.stack([120 + 100 * np.sin(xx / W * 3 + seed), 140 + 90 * np.cos(yy / H * 2.5 + seed), 190 - 60 * (xx / W)], -1)
    img = np.clip(base, 0, 255).astype(np.uint8)
    for _ in range(6):
        c = tuple(int(v) for v in rng.randint(30, 255, 3))
        cv2.circle(img, (int(rng.randint(0, W)), int(rng.randint(0, H))), int(rng.randint(20, 90)), c, -1, cv2.LINE_AA)
    cv2.putText(img, "Rx", (int(W * .38), int(H * .62)), cv2.FONT_HERSHEY_SIMPLEX, 3.2, (255, 255, 255), 8, cv2.LINE_AA)
    img = cv2.resize(img, (px_w, px_h), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".png", img)[1].tobytes()


# ── geometry ──────────────────────────────────────────────────────────────
def union(rects):
    rects = [r for r in rects if r]
    return [min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)] if rects else None


def text_height(text, fname, size, width) -> float:
    f = font(fname)
    lines = 0
    for para in text.split("\n"):
        cur, n = "", 1
        for w in para.split(" "):
            t = f"{cur} {w}" if cur else w
            if f.text_length(t, fontsize=size) <= width:
                cur = t
            else:
                n, cur = n + 1, w
        lines += n
    return lines * size * (f.ascender - f.descender)


def refit(el):
    """Recompute the box of auto-height text after its text/size changed."""
    if el["kind"] == "text" and el.get("auto"):
        x0, y0, x1, _ = el["rect"]
        el["rect"] = (x0, y0, x1, y0 + text_height(el["text"], el["font"], el["size"], x1 - x0) + 1.0)


def braille_rect(el):
    cells = el["cells"]
    p = el["pitch"]
    w = len(cells) * el["cell_pitch"]
    return (el["x"] - 2, el["y"] - 2, el["x"] + w, el["y"] + 2 * p + 2 + el["r"])


def rect_of(el) -> tuple:
    k = el["kind"]
    if k in ("text", "rect", "logo", "image"):
        return tuple(el["rect"])
    if k == "barcode":
        w, h = barcode_size(el)
        x, y = el["x"], el["y"]
        extra = (12 if el.get("printed") else 2)
        if el.get("rotated"):
            return (x - 2, y - 2, x + h + extra + 8, y + w + 2)
        return (x - 10, y - 2, x + w + 2, y + h + extra)
    if k == "braille":
        return braille_rect(el)
    if k == "line":
        (x0, y0), (x1, y1) = el["p0"], el["p1"]
        return (min(x0, x1) - 1, min(y0, y1) - 1, max(x0, x1) + 1, max(y0, y1) + 1)
    if k == "dot":
        cx, cy = el["c"]
        return (cx - el["r"] - 1, cy - el["r"] - 1, cx + el["r"] + 1, cy + el["r"] + 1)
    if k == "circle":
        cx, cy = el["c"]
        return (cx - el["r"], cy - el["r"], cx + el["r"], cy + el["r"])
    cx, cy = el["c"]  # icons
    return (cx - 12, cy - 12, cx + 12, cy + 12)


# ── drawing ───────────────────────────────────────────────────────────────
def _c(rgb):
    return None if rgb is None else tuple(v / 255 for v in rgb)


def _draw_barcode(page, el, oc):
    mw, h, x, y = el["mw"], el["h"], el["x"], el["y"]
    black = dict(color=None, fill=_c(el.get("bar_color", (0, 0, 0))), oc=oc)
    if el["fmt"] == "ean13":
        mods = ean13_modules(el["value"])
        kind = "1d"
    else:
        kind, mods = zx_modules(el["fmt"], el["value"])
    if kind == "1d":
        i = 0
        while i < len(mods):
            if mods[i] == "1":
                j = i
                while j < len(mods) and mods[j] == "1":
                    j += 1
                r = pymupdf.Rect(x, y + i * mw, x + h, y + j * mw) if el.get("rotated") else pymupdf.Rect(x + i * mw, y, x + j * mw, y + h)
                page.draw_rect(r, **black)
                i = j
            else:
                i += 1
        p = el.get("printed")
        if p:
            n = len(mods)
            if el["fmt"] == "ean13":
                groups = [(p[0], -8, -1), (p[1:7], 3, 45), (p[7:], 50, 92)]
                size = 7.5
            else:
                groups = [(p, 0, n)]
                size = el.get("ps", 5.5)
            for txt, a, b in groups:
                if el.get("rotated"):
                    page.insert_text((x + h + 9, y + b * mw), txt, fontsize=size, fontname="arial", rotate=90, oc=oc)
                elif el["fmt"] == "ean13":
                    page.insert_text((x + a * mw, y + h + 9), txt, fontsize=size, fontname="arial", oc=oc)
                else:
                    tw = font("arial").text_length(txt, fontsize=size)
                    page.insert_text((x + (n * mw - tw) / 2, y + h + size + 1), txt, fontsize=size, fontname="arial", oc=oc)
    else:
        for r_i in range(mods.shape[0]):
            c_i = 0
            while c_i < mods.shape[1]:
                if mods[r_i, c_i]:
                    j = c_i
                    while j < mods.shape[1] and mods[r_i, j]:
                        j += 1
                    page.draw_rect(pymupdf.Rect(x + c_i * mw, y + r_i * mw, x + j * mw, y + (r_i + 1) * mw), **black)
                    c_i = j
                else:
                    c_i += 1


def render(spec: dict, path, order=None):
    doc = pymupdf.open()
    ocgs = {n: doc.add_ocg(n, on=on) for n, on in spec.get("layers", {}).items()}
    for pg in spec["pages"]:
        page = doc.new_page(width=pg["size"][0], height=pg["size"][1])
        used = set()
        E = pg["elements"]
        for eid in (order if order is not None else pg["order"]):
            el = E.get(eid)
            if el is None:
                continue
            oc = ocgs.get(el.get("layer"), 0)
            k = el["kind"]
            if k == "rect":
                page.draw_rect(pymupdf.Rect(*el["rect"]), color=_c(el.get("stroke")), fill=_c(el.get("fill")), width=el.get("width", 0.8), oc=oc)
            elif k == "line":
                page.draw_line(el["p0"], el["p1"], color=_c(el.get("color", GREY)), width=el.get("width", 0.5), oc=oc)
            elif k == "circle":
                page.draw_circle(el["c"], el["r"], color=_c(el.get("stroke")), fill=_c(el.get("fill")), width=el.get("width", 0.8), oc=oc)
            elif k == "dot":
                page.draw_circle(el["c"], el["r"], color=None, fill=_c(el.get("color", BLACK)), oc=oc)
            elif k == "text":
                if not el["text"]:
                    continue
                fn = el["font"]
                if fn not in used:
                    page.insert_font(fontname=fn, fontfile=str(FONT_DIR / FONT_FILES[fn]))
                    used.add(fn)
                x0, y0, x1, y1 = el["rect"]
                rot = el.get("rotate", 0)
                r = pymupdf.Rect(x0, y0, x1, y1 + 60) if rot == 0 else pymupdf.Rect(x0, y0, x1 + 60, y1) if rot == 90 else pymupdf.Rect(x0 - 60, y0, x1, y1)
                left = page.insert_textbox(r, el["text"], fontsize=el["size"], fontname=fn, color=_c(el.get("color", BLACK)),
                                           align=el.get("align", 0), rotate=rot, render_mode=3 if el.get("hidden") else 0, oc=oc)
                if left < 0:
                    raise RuntimeError(f"text does not fit: {eid} {el['text']!r}")
            elif k == "logo":
                page.draw_circle((41, 39), 17, color=_c(WHITE), width=2, oc=oc)
                page.draw_polyline([(35, 46), (47, 46), (41, 30), (35, 46)], color=None, fill=_c(el.get("color", (255, 196, 0))), oc=oc)
            elif k.startswith("icon_"):
                cx, cy = el["c"]
                col = el.get("color", GREY)
                page.draw_circle((cx, cy), 11, color=_c(GREY), width=0.8, oc=oc)
                if k == "icon_sun":
                    page.draw_circle((cx, cy), 4, color=None, fill=_c(col), oc=oc)
                    for a in range(0, 360, 45):
                        dx, dy = math.cos(math.radians(a)), math.sin(math.radians(a))
                        page.draw_line((cx + dx * 6, cy + dy * 6), (cx + dx * 8.5, cy + dy * 8.5), color=_c(col), width=1, oc=oc)
                elif k == "icon_kids":
                    page.draw_circle((cx, cy - 4), 2.6, color=None, fill=_c(col), oc=oc)
                    page.draw_polyline([(cx - 4, cy + 6), (cx + 4, cy + 6), (cx, cy - 1), (cx - 4, cy + 6)], color=None, fill=_c(col), oc=oc)
                elif k == "icon_temp":
                    page.draw_rect(pymupdf.Rect(cx - 1.5, cy - 7, cx + 1.5, cy + 2), color=None, fill=_c(col), oc=oc)
                    page.draw_circle((cx, cy + 4.5), 3, color=None, fill=_c(col), oc=oc)
            elif k == "image":
                x0, y0, x1, y1 = el["rect"]
                w_px = max(8, int(el["ppi"] * (x1 - x0) / 72))
                h_px = max(8, int(el["ppi"] * (y1 - y0) / 72))
                page.insert_image(pymupdf.Rect(*el["rect"]), stream=make_image(el["seed"], w_px, h_px), oc=oc)
            elif k == "barcode":
                _draw_barcode(page, el, oc)
            elif k == "braille":
                for i, cell in enumerate(el["cells"]):
                    for d in cell:
                        cx_, ry = _DOT_POS[d]
                        page.draw_circle((el["x"] + i * el["cell_pitch"] + cx_ * el["pitch"], el["y"] + ry * el["pitch"]), el["r"],
                                         color=None, fill=(0, 0, 0), oc=oc)
        if pg.get("trimbox"):
            page.set_trimbox(pymupdf.Rect(*pg["trimbox"]))
    if spec.get("meta"):
        doc.set_metadata(spec["meta"])
    doc.save(str(path), garbage=3, deflate=True)
    doc.close()


def flatten(src, dst, dpi: int):
    """Image-only PDF: what you get when artwork is flattened / outlined and rasterised."""
    s = pymupdf.open(str(src))
    d = pymupdf.open()
    for pg in s:
        pix = pg.get_pixmap(dpi=dpi, alpha=False)
        np_ = d.new_page(width=pg.rect.width, height=pg.rect.height)
        np_.insert_image(np_.rect, pixmap=pix)
    d.save(str(dst), deflate=True)
