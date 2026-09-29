"""PDF-vs-PDF packaging proofing engine.

Three independent checks run on every page pair, then get merged so one real
difference produces one finding (not three):

  1. Text     - read the words straight out of each PDF (no OCR), match text
                blocks between files, then diff word-by-word.
  2. Barcode  - decode every barcode in both renders, compare payloads, check
                digits, orientation, position and size. Also checks that the
                printed human-readable digits agree with what the bars encode.
  3. Visual   - render both pages, compare in CIE-Lab colour space, cluster the
                changed pixels, then classify each cluster (moved / removed /
                added / recoloured / restyled / changed).
"""
from __future__ import annotations

import dataclasses
import difflib
import math
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np
import pymupdf
import zxingcpp

from . import align, ocr
from .imaging import open_pdf

MM = 72 / 25.4  # PDF points per millimetre
SEV_RANK = {"info": 0, "minor": 1, "major": 2, "critical": 3}
UNITS = re.compile(r"^(mg|ml|mcg|µg|μg|g|kg|iu|l|%)\.?$", re.I)
KEY_SYMBOLS = set("°%±µμ/")


@dataclass
class Config:
    dpi: int = 300
    delta_e: float = 3.0           # a pixel is "changed" above this CIE76 dE (1/255 drift is ~0.5)
    min_area_px: int = 6           # ignore specks smaller than this
    merge_mm: float = 0.8          # changed pixels closer than this belong to one region
    size_tol_pt: float = 0.75      # page size tolerance
    angle_tol: float = 2.0         # barcode rotation tolerance, degrees
    barcode_shift_mm: float = 0.5
    barcode_shift_mm_raster: float = 1.2  # looser: low-dpi rasterisation jitters a decoded barcode's measured bbox
    barcode_min_contrast: float = 0.5     # (Rmax-Rmin) reflectance range below this -> likely unscannable
    barcode_min_reflectance: float = 0.5  # lightest tone in the symbol below this -> background too dark
    barcode_quiet_zone_mm: float = 2.0    # required clear margin each side of the bars
    barcode_scale_tol: float = 0.03
    move_tol_mm: float = 0.25
    move_search_mm: float = 15.0
    move_max_residual: float = 0.06  # a 'move' must leave <=6% of its ink still disagreeing after realignment
    min_text_match: float = 0.5
    raster_delta_e: float = 16.0   # looser tolerance near edges when a page is image-only (resampling noise)
    raster_blur: float = 3.0       # px at cfg.dpi; tuned on the image-only samples (see README)
    raster_delta_e_tight: float = 4.0  # tolerance in genuinely flat regions, where two renders of the
                                        # same artwork can't drift - catches solid-fill colour shifts
                                        # the loose texture-safe threshold alone would miss
    raster_flat_var: float = 6.0       # local-variance threshold below which a region counts as "flat"
                                        # (both grayscale channels near-constant in the local window)
    ocr: bool = True                   # describe flagged regions with OCR when an engine is installed
    ocr_max_regions: int = 25          # per page; OCR is the slow step
    page_align_min_sim: float = 0.35   # when page counts differ, pages pair up only above this similarity
    register: bool = True             # detect and undo a whole-page shift / scale / rotation / photo before comparing
    separation_dpi: int = 100          # CMYK plate comparison resolution
    separation_tol: float = 12.0       # % ink difference on any one plate that counts as a change
    image_ppi_drop: float = 0.85       # sample image effective-ppi / reference below this -> resolution finding


@dataclass
class Finding:
    category: str                  # text | barcode | graphic | layout | color | format | structure | info | braille | layer
    kind: str
    severity: str                  # critical | major | minor | info
    page: int
    message: str
    a_text: str = ""
    b_text: str = ""
    bbox_a: list | None = None     # PDF points [x0, y0, x1, y1]
    bbox_b: list | None = None
    detail: dict = field(default_factory=dict)
    id: int = 0
    confidence: str = "high"       # high = read directly from the PDF / decoded; medium = inferred from pixels or a proxy


@dataclass
class Result:
    findings: list
    pages: list                    # per-page render data, used by the HTML report
    warnings: list
    coverage: list = field(default_factory=list)   # per page: which checks ran, which were skipped and why
    attention: list = field(default_factory=list)  # not differences, but something a person should look at

    @property
    def coverage_limited(self) -> bool:
        return any(c["limited"] for c in self.coverage)

    @property
    def verdict(self) -> str:
        """FAIL: a major/critical difference. REVIEW: only minor differences, or something needs a human
        eye. PASS: nothing found by any check that ran (see coverage_limited for what could not run)."""
        real = [f for f in self.findings if f.severity != "info"]
        if any(SEV_RANK[f.severity] >= 2 for f in real):
            return "FAIL"
        return "REVIEW" if real or self.attention else "PASS"

    def to_dict(self) -> dict:
        counts = {s: sum(f.severity == s for f in self.findings) for s in ("critical", "major", "minor", "info")}
        return dict(verdict=self.verdict, counts=counts, coverage_limited=self.coverage_limited,
                    coverage=self.coverage, attention=self.attention, warnings=self.warnings,
                    findings=[asdict(f) for f in self.findings])


# ── small helpers ─────────────────────────────────────────────────────────
def rgb2lab(img) -> np.ndarray:
    """CIE-Lab (D65) of an RGB uint8 image or float image scaled 0..1. OpenCV's conversion: same numbers as
    scikit-image's to within 0.3 dE, about four times faster."""
    a = np.asarray(img)
    a = a.astype(np.float32) / 255.0 if a.dtype == np.uint8 else a.astype(np.float32)
    return cv2.cvtColor(a, cv2.COLOR_RGB2Lab)


def lab_dist(a: np.ndarray, b: np.ndarray, rows: int = 256) -> np.ndarray:
    """Per-pixel CIE-Lab distance between two RGB images. Every pixel is converted independently, so doing it in strips
    gives exactly the same numbers as converting whole pages, without holding several full-size float arrays at once."""
    out = np.empty(a.shape[:2], np.float32)
    for y in range(0, a.shape[0], rows):
        out[y:y + rows] = np.linalg.norm(rgb2lab(a[y:y + rows]) - rgb2lab(b[y:y + rows]), axis=-1)
    return out


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).replace(" ", " ")


def _union(rects):
    rects = [r for r in rects if r]
    if not rects:
        return None
    return [min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)]


def _area(r):
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _inter(a, b):
    return _area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def _iou(a, b):
    i = _inter(a, b)
    u = _area(a) + _area(b) - i
    return i / u if u else 0.0


def _center(r):
    return ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)


def _dist(a, b):
    (ax, ay), (bx, by) = _center(a), _center(b)
    return math.hypot(ax - bx, ay - by)


def _pad(r, p):
    return [r[0] - p, r[1] - p, r[2] + p, r[3] + p]


# ── 1. text ───────────────────────────────────────────────────────────────
class _DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def _cluster(items, rects, near):
    """Union items whose rects satisfy near(a, b). Sweeps by y so it stays fast on dense pages."""
    order = sorted(range(len(items)), key=lambda i: rects[i][1])
    dsu = _DSU(len(items))
    reach = max((r[3] - r[1] for r in rects), default=0) * 3
    for oi, i in enumerate(order):
        for j in order[oi + 1:]:
            if rects[j][1] - rects[i][3] > reach:
                break
            if near(rects[i], rects[j]):
                dsu.union(i, j)
    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        groups.setdefault(dsu.find(i), []).append(i)
    return list(groups.values())


def _text_blocks(page) -> list[dict]:
    """Group words into paragraphs using geometry only.

    MuPDF's own blocks depend on the order drawing commands were written, which
    differs between export tools for identical-looking artwork. Here a line is
    'words side by side on one baseline' and a paragraph is 'lines stacked
    tightly with similar text height', so the same page always segments the
    same way.
    """
    ws = [(w[0], w[1], w[2], w[3], _norm(w[4])) for w in page.get_text("words") if w[4].strip()]
    if not ws:
        return []
    rects = [w[:4] for w in ws]

    def same_line(a, b):
        ha, hb = a[3] - a[1], b[3] - b[1]
        overlap = min(a[3], b[3]) - max(a[1], b[1])
        gap = max(a[0], b[0]) - min(a[2], b[2])
        return overlap >= 0.6 * min(ha, hb) and gap <= 0.9 * max(ha, hb)

    lines = []
    for grp in _cluster(ws, rects, same_line):
        wl = sorted((ws[i] for i in grp), key=lambda w: w[0])
        lines.append(dict(words=wl, rect=_union([w[:4] for w in wl])))

    def same_para(a, b):
        ha, hb = a[3] - a[1], b[3] - b[1]
        gap = max(a[1], b[1]) - min(a[3], b[3])
        xo = min(a[2], b[2]) - max(a[0], b[0])
        return gap <= 0.35 * min(ha, hb) and xo >= 0.3 * min(a[2] - a[0], b[2] - b[0]) and 0.75 <= ha / hb <= 1.33

    out = []
    for grp in _cluster(lines, [ln["rect"] for ln in lines], same_para):
        ls = sorted((lines[i] for i in grp), key=lambda ln: ((ln["rect"][1] + ln["rect"][3]) / 2, ln["rect"][0]))
        wl = [w for ln in ls for w in ln["words"]]
        out.append(dict(words=wl, rect=_union([w[:4] for w in wl]), text=" ".join(w[4] for w in wl)))
    return out


def _match_blocks(ba, bb, cfg):
    cand = []
    for i, a in enumerate(ba):
        for j, b in enumerate(bb):
            sm = difflib.SequenceMatcher(None, a["text"], b["text"], autojunk=False)
            if sm.real_quick_ratio() < cfg.min_text_match or sm.quick_ratio() < cfg.min_text_match:
                continue
            r = sm.ratio()
            if r >= cfg.min_text_match:
                cand.append((r + 0.2 * max(0.0, 1 - _dist(a["rect"], b["rect"]) / (30 * MM)), i, j))
    cand.sort(reverse=True)
    ua, ub, pairs = set(range(len(ba))), set(range(len(bb))), []
    for _s, i, j in cand:
        if i in ua and j in ub:
            pairs.append((i, j)); ua.discard(i); ub.discard(j)
    # leftovers that sit on top of each other were rewritten wholesale
    for i in sorted(ua):
        for j in sorted(ub):
            if _iou(ba[i]["rect"], bb[j]["rect"]) > 0.3:
                pairs.append((i, j)); ua.discard(i); ub.discard(j)
                break
    return pairs, sorted(ua), sorted(ub)


def _text_severity(a: list[str], b: list[str]) -> str:
    sa, sb = " ".join(a), " ".join(b)
    if re.search(r"\d", sa + sb):
        return "critical"
    if sa.casefold() == sb.casefold():
        return "minor"
    if any(UNITS.match(t) for t in a + b):
        return "critical"
    strip = lambda s: re.sub(r"[\W_]+", "", s.casefold())
    if strip(sa) == strip(sb):
        return "major" if (set(sa + sb) & KEY_SYMBOLS) else "minor"
    return "major"


# Unicode ranges wide enough to tell scripts apart at a glance, without pulling in a language-ID
# library: this only needs to catch "the wrong language entirely" (a Cyrillic leaflet where an
# English one belongs), not distinguish e.g. French from Spanish (see compare_language docstring).
_SCRIPTS = [
    ("Latin", 0x0041, 0x024F), ("Cyrillic", 0x0400, 0x04FF), ("Greek", 0x0370, 0x03FF),
    ("Arabic", 0x0600, 0x06FF), ("Hebrew", 0x0590, 0x05FF), ("Devanagari", 0x0900, 0x097F),
    ("Thai", 0x0E00, 0x0E7F), ("Han", 0x4E00, 0x9FFF), ("Hiragana/Katakana", 0x3040, 0x30FF),
    ("Hangul", 0xAC00, 0xD7A3),
    ("Arabic", 0xFB50, 0xFDFF), ("Arabic", 0xFE70, 0xFEFF),  # presentation forms: how shaped Arabic is stored in most PDFs
]


def _script_counts(text: str) -> Counter:
    counts = Counter()
    for ch in text:
        cp = ord(ch)
        for name, lo, hi in _SCRIPTS:
            if lo <= cp <= hi:
                counts[name] += 1
                break
    return counts


def compare_language(pa, pb, page_no) -> list[Finding]:
    """Whole page in the wrong script/language - e.g. a Cyrillic leaflet packed where an English one
    belongs. Deterministic (Unicode script of the PDF's own text, not OCR or a language-ID model), so
    it only catches a different alphabet, not e.g. French swapped for Spanish - same-script language
    mixups need real language detection and aren't covered here (see README)."""
    ca, cb = _script_counts(pa.get_text()), _script_counts(pb.get_text())
    na, nb = sum(ca.values()), sum(cb.values())
    if na < 20 or nb < 20:  # too little alphabetic text on one side to be confident either way
        return []
    dom_a, cnt_a = ca.most_common(1)[0]
    dom_b, cnt_b = cb.most_common(1)[0]
    if dom_a == dom_b or cnt_a / na < 0.6 or cnt_b / nb < 0.6:  # same script, or neither side is clearly one script
        return []
    return [Finding("text", "language_mismatch", "critical", page_no,
                    f"Page {page_no + 1}: the reference's text is {dom_a} script but the sample's text is "
                    f"{dom_b} script - check that the correct language variant of the artwork was used.",
                    a_text=dom_a, b_text=dom_b, confidence="high")]


def compare_text(pa, pb, page_no, cfg, k: float = 1.0) -> list[Finding]:
    ba, bb = _text_blocks(pa), _text_blocks(pb)
    if not ba and not bb:
        return []
    out: list[Finding] = []
    pairs, ua, ub = _match_blocks(ba, bb, cfg)
    for i in ua:
        out.append(Finding("text", "removed", "critical" if re.search(r"\d", ba[i]["text"]) else "major", page_no,
                           f'Text missing from sample: "{ba[i]["text"]}"', a_text=ba[i]["text"], bbox_a=list(ba[i]["rect"]),
                           detail=dict(whole_block=True, words=[list(w) for w in ba[i]["words"]])))
    for j in ub:
        out.append(Finding("text", "added", "critical" if re.search(r"\d", bb[j]["text"]) else "major", page_no,
                           f'Extra text in sample: "{bb[j]["text"]}"', b_text=bb[j]["text"], bbox_b=list(bb[j]["rect"]),
                           detail=dict(whole_block=True, words=[list(w) for w in bb[j]["words"]])))
    for i, j in pairs:
        a, b = ba[i], bb[j]
        if a["text"] == b["text"]:
            continue
        blocks = dict(block_a=list(a["rect"]), block_b=list(b["rect"]))  # lets the visual pass treat re-flow as explained
        sa, sb = _styles(pa, a["rect"]), _styles(pb, b["rect"], k)
        if sa != sb:
            out.append(Finding("format", "text_style", "minor", page_no,
                               "Text style changed: " + ", ".join(f"{s} pt {f}" for s, f in sorted(sa)) + " → " + ", ".join(f"{s} pt {f}" for s, f in sorted(sb)),
                               bbox_a=list(a["rect"]), bbox_b=list(b["rect"]), detail=dict(before=sorted(sa), after=sorted(sb), **blocks)))
        wa, wb = [w[4] for w in a["words"]], [w[4] for w in b["words"]]
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            ra = _union([w[:4] for w in a["words"][i1:i2]]) or _union([w[:4] for w in a["words"][max(0, i1 - 1):i1 + 1]])
            rb = _union([w[:4] for w in b["words"][j1:j2]]) or _union([w[:4] for w in b["words"][max(0, j1 - 1):j1 + 1]])
            ta, tb = " ".join(wa[i1:i2]), " ".join(wb[j1:j2])
            kind = {"replace": "changed", "delete": "removed", "insert": "added"}[tag]
            msg = {"changed": f'Text changed: "{ta}" → "{tb}"', "removed": f'Text removed: "{ta}"', "added": f'Text added: "{tb}"'}[kind]
            moved_words = [list(w) for w in (a["words"][i1:i2] if tag == "delete" else b["words"][j1:j2] if tag == "insert" else [])]
            out.append(Finding("text", kind, _text_severity(wa[i1:i2], wb[j1:j2]), page_no, msg,
                               a_text=ta, b_text=tb, bbox_a=ra and list(ra), bbox_b=rb and list(rb),
                               detail=dict(context_a=a["text"][:120], context_b=b["text"][:120], words=moved_words, **blocks)))
    out = _reconcile_text(out, page_no)
    out = _reconcile_moves(out, page_no)
    for f in out:
        f.detail.pop("words", None)
        f.detail.pop("whole_block", None)
    return out


def _reconcile_moves(fs: list[Finding], page_no: int, tol_mm: float = 0.25) -> list[Finding]:
    """Text that disappears from one spot and appears, word for word, elsewhere on the page was moved, not deleted
    and re-typed. An 'added' block made up exactly of 'removed' pieces is split back into those pieces: pieces that
    now sit somewhere else become one 'moved' finding each; pieces still in place were only regrouped (no finding)."""
    rem = [f for f in fs if f.category == "text" and f.kind == "removed" and f.detail.get("words")]
    add = [f for f in fs if f.category == "text" and f.kind == "added" and f.detail.get("words")]
    drop: set[int] = set()
    extra = []
    for a in add:
        aw, pos, used = [w[4] for w in a.detail["words"]], 0, []
        while pos < len(aw):
            hit = next((r for r in rem if id(r) not in drop and all(r is not u[0] for u in used) and [w[4] for w in r.detail["words"]] == aw[pos:pos + len(r.detail["words"])]), None)
            if hit is None:
                break
            used.append((hit, pos))
            pos += len(hit.detail["words"])
        if pos != len(aw) or not used:
            continue
        for r, at in used:
            ra = _union([w[:4] for w in r.detail["words"]])
            rb = _union([w[:4] for w in a.detail["words"][at:at + len(r.detail["words"])]])
            d = _dist(ra, rb) / MM
            if d > tol_mm:
                txt = " ".join(w[4] for w in r.detail["words"])
                extra.append(Finding("layout", "moved", "minor" if d < 2 else "major", page_no,
                                     f'Text "{txt}" moved {d:.1f} mm; wording unchanged', a_text=txt, b_text=txt,
                                     bbox_a=ra, bbox_b=rb, detail=dict(mm=d, words=[])))
            drop.add(id(r))
        drop.add(id(a))
    return [f for f in fs if id(f) not in drop] + extra


def _find_sub(seq, sub):
    n = len(sub)
    for i in range(len(seq) - n + 1):
        if seq[i:i + n] == sub:
            return i
    return None


def _reconcile_text(fs: list[Finding], page_no: int) -> list[Finding]:
    """Deleting a line can split one paragraph into two, so the same words show up as 'removed' in one
    place and 'added' in another. Cancel words that appear on both sides; keep only the genuine residue."""
    def residue(f, idx, n, side):
        ws = f.detail["words"]
        parts = [ws[:idx], ws[idx + n:]]
        made = []
        for part in parts:
            if not part:
                continue
            txt = " ".join(w[4] for w in part)
            rect = _union([w[:4] for w in part])
            kind = "removed" if side == "a" else "added"
            made.append(Finding("text", kind, _text_severity([w[4] for w in part], []), page_no,
                                (f'Text removed: "{txt}"' if side == "a" else f'Text added: "{txt}"'),
                                a_text=txt if side == "a" else "", b_text=txt if side == "b" else "",
                                bbox_a=rect if side == "a" else None, bbox_b=rect if side == "b" else None,
                                detail=dict(words=[list(w) for w in part], **{k: v for k, v in f.detail.items() if k.startswith("block_")})))
        return made

    changed = True
    while changed:
        changed = False
        for whole_kind, other_kind, side in (("added", "removed", "a"), ("removed", "added", "b")):
            wholes = [f for f in fs if f.category == "text" and f.kind == whole_kind and f.detail.get("whole_block") and f.detail.get("words")]
            others = [f for f in fs if f.category == "text" and f.kind == other_kind and f.detail.get("words")]
            for w in wholes:
                ww = [x[4] for x in w.detail["words"]]
                for o in others:
                    ow = [x[4] for x in o.detail["words"]]
                    idx = _find_sub(ow, ww)
                    if idx is None:
                        continue
                    fs = [f for f in fs if f is not w and f is not o] + residue(o, idx, len(ww), side)
                    changed = True
                    break
                if changed:
                    break
            if changed:
                break
    return fs


# ── 2. barcodes ───────────────────────────────────────────────────────────
def _decode(img: np.ndarray, dpi: float) -> list[dict]:
    k = 72 / dpi
    out = []
    for r in zxingcpp.read_barcodes(img, return_errors=True):
        if not r.text:
            continue  # a decode error with nothing decoded is not a barcode
        p = r.position
        pts = [p.top_left, p.top_right, p.bottom_right, p.bottom_left]
        xs, ys = [q.x for q in pts], [q.y for q in pts]
        out.append(dict(
            text=r.text, format=r.format.name, valid=bool(r.valid), angle=float(r.orientation),
            bbox=[min(xs) * k, min(ys) * k, max(xs) * k, max(ys) * k],
            length=math.hypot(p.top_right.x - p.top_left.x, p.top_right.y - p.top_left.y) * k,
        ))
    return out


def _read_codes(img: np.ndarray, dpi: int) -> list[dict]:
    """Decode at the render resolution, then again upscaled: a small or tightly-printed symbol that
    one pass misses is often readable in the other. Both sides go through the identical procedure, so
    a difference in what decodes is itself a signal rather than a bias."""
    out = _decode(img, dpi)
    up = cv2.resize(img, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)
    for c in _decode(up, dpi * 1.6):
        if not c["text"] or not c["valid"]:
            continue  # the extra pass may only ADD well-formed symbols; it must never invent a broken one
        if not any(c["text"] == o["text"] and c["format"] == o["format"] and _dist(c["bbox"], o["bbox"]) < 8 * MM for o in out):
            out.append(c)
    return out


def _orphan_digit_strings(page, codes: list[dict]) -> list[tuple]:
    """Runs of 8/12/13/14 digits that look like a printed barcode number but have no decoded barcode
    beside them - the symbol may be missing, damaged, or just not decodable, and the barcode check
    can't vouch for it either way."""
    out = []
    for blk in _text_blocks(page):
        digits = blk["text"].replace(" ", "")
        if digits.isdigit() and len(digits) in (8, 12, 13, 14):
            zone = _pad(blk["rect"], 30)
            if not any(_inter(c["bbox"], zone) > 0 for c in codes):
                out.append((digits, blk["rect"]))
    return out


def _print_quality(img: np.ndarray, bbox, dpi: float) -> dict:
    """Practical print-quality signal for a barcode: reflectance range and darkest/lightest tone
    within its own footprint, robust to outlier pixels (2nd/98th percentile, not literal min/max).
    Not a full ISO/IEC 15416 grade (that needs multiple scanlines, edge-determination and a
    modulation/defect metric) - a single, bounded proxy for the most common real failure: bars and
    background too close in tone, or the background itself too dark, to scan reliably."""
    k = dpi / 72
    x0, y0, x1, y1 = (int(v * k) for v in bbox)
    x0, y0 = max(0, x0), max(0, y0)
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return dict(contrast=1.0, min_reflectance=1.0, max_reflectance=1.0)
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    lo, hi = float(np.percentile(gray, 2)), float(np.percentile(gray, 98))
    return dict(contrast=hi - lo, min_reflectance=lo, max_reflectance=hi)


def _quiet_zone_ok(img: np.ndarray, bbox, dpi: float, margin_mm: float) -> bool:
    """Checks the margin immediately left/right of the barcode's footprint for other print content.
    A scanner needs a clear quiet zone before the first bar and after the last; this is a bounded
    proxy for that (fixed margin, not the ISO 10x-narrow-module rule, which needs the module width)."""
    k = dpi / 72
    m = int(margin_mm * MM * k)
    x0, y0, x1, y1 = (int(v * k) for v in bbox)
    x0, y0, y1 = max(0, x0), max(0, y0), min(img.shape[0], y1)
    for zx0, zx1 in ((x0 - m, x0), (x1, x1 + m)):
        if zx0 < 0 or zx1 > img.shape[1] or y1 <= y0:
            continue
        zone = img[y0:y1, zx0:zx1]
        if zone.size == 0:
            continue
        gray = cv2.cvtColor(zone, cv2.COLOR_RGB2GRAY)
        if (gray < 200).mean() > 0.1:  # >10% of the quiet zone isn't blank paper
            return False
    return True


def _printed_digits(code: dict, page) -> tuple[str, list] | None:
    """Digits printed next to a barcode (the human-readable line), read from the text layer.
    Returns (digits, bounding box of those digits) so a mismatch can be localised on the digits too."""
    zone = _pad(code["bbox"], 16)
    ws = [w for w in page.get_text("words") if re.fullmatch(r"\d+", w[4]) and _inter(w[:4], zone) > 0.5 * _area(w[:4])]
    if not ws:
        return None
    vertical = abs(code["angle"]) in (90.0, 270.0)
    ws.sort(key=lambda w: w[1] if vertical else w[0])
    s = "".join(w[4] for w in ws)
    return (s, _union([w[:4] for w in ws])) if len(s) >= 8 else None


def _ocr_printed_digits(img: np.ndarray, code: dict, dpi: float) -> tuple[str, list] | None:
    """Same question for image-only artwork, where there is no text layer to read: OCR the strip around
    the bars. Flagged as medium confidence by the caller - it is a reading of pixels, not of the file."""
    if not ocr.available():
        return None
    k = dpi / 72
    x0, y0, x1, y1 = code["bbox"]
    box = _pad(code["bbox"], 14) if abs(code["angle"]) in (90.0, 270.0) else [x0 - 10, y0 - 2, x1 + 8, y1 + 16]
    xa, ya, xb, yb = (max(0, int(v * k)) for v in box)
    txt = ocr.read(img[ya:yb, xa:xb], min_conf=0.6, by_x=True)  # the number is one line: read it strictly left to right
    s = re.sub(r"\D", "", txt)
    return (s, [xa / k, ya / k, xb / k, yb / k]) if len(s) >= 8 else None


def compare_barcodes(img_a, img_b, pa, pb, page_no, cfg, raster=False, codes=None, H=None) -> list[Finding]:
    ca, cb = codes if codes is not None else (_read_codes(img_a, cfg.dpi), _read_codes(img_b, cfg.dpi))
    cb_own = cb
    out: list[Finding] = []

    for side, codes, page, img in (("reference", ca, pa, img_a), ("sample", cb, pb, img_b)):
        live = bool(page.get_text("words"))
        for c in codes:
            got = _printed_digits(c, page) if live else _ocr_printed_digits(img, c, cfg.dpi)
            digits = re.sub(r"\D", "", c["text"])
            if got and digits and got[0] != digits:
                printed, prect = got
                src = "read from the text layer" if live else "read by OCR"
                out.append(Finding("barcode", "digits_mismatch", "critical", page_no,
                                   f"Barcode in {side} encodes {digits} but the printed digits read {printed}",
                                   a_text=digits if side == "reference" else "", b_text=digits if side == "sample" else "",
                                   bbox_a=_union([c["bbox"], prect]) if side == "reference" else None,
                                   bbox_b=_union([c["bbox"], prect]) if side == "sample" else None,
                                   detail=dict(printed=printed, encoded=digits, source=src),
                                   confidence="high" if live else "medium"))

    if H is not None:  # position / size are compared in the reference's frame once the page is registered
        sH = float(np.sqrt(abs(np.linalg.det(H[:2, :2]))))
        cb = [dict(c, bbox=align.map_rect(H, c["bbox"]), length=c["length"] * sH) for c in cb]
    ua, ub, pairs = list(ca), list(cb), []
    for a in list(ua):
        same = [b for b in ub if b["text"] == a["text"] and b["format"] == a["format"]]
        if same:
            b = min(same, key=lambda b: _dist(a["bbox"], b["bbox"]))
            pairs.append((a, b, True)); ua.remove(a); ub.remove(b)
    for a in list(ua):
        near = [b for b in ub if _dist(a["bbox"], b["bbox"]) < 30 * MM]
        if near:
            b = min(near, key=lambda b: _dist(a["bbox"], b["bbox"]))
            pairs.append((a, b, False)); ua.remove(a); ub.remove(b)

    for a, b, same_payload in pairs:
        if not same_payload:
            if not b["valid"]:
                out.append(Finding("barcode", "invalid_checksum", "critical", page_no,
                                   f"Sample barcode {b['text']} has an INVALID check digit (scanners will reject it); reference is {a['text']}",
                                   a_text=a["text"], b_text=b["text"], bbox_a=a["bbox"], bbox_b=b["bbox"]))
            else:
                out.append(Finding("barcode", "payload_changed", "critical", page_no,
                                   f"Barcode value changed: {a['text']} → {b['text']}",
                                   a_text=a["text"], b_text=b["text"], bbox_a=a["bbox"], bbox_b=b["bbox"]))
            continue
        if not b["valid"]:
            out.append(Finding("barcode", "invalid_checksum", "critical", page_no, f"Sample barcode {b['text']} has an invalid check digit",
                               a_text=a["text"], b_text=b["text"], bbox_a=a["bbox"], bbox_b=b["bbox"]))
        da = (b["angle"] - a["angle"] + 180) % 360 - 180
        if abs(da) > cfg.angle_tol:
            out.append(Finding("barcode", "orientation", "major", page_no,
                               f"Barcode {a['text']} is rotated {da:+.0f}° relative to the reference",
                               a_text=a["text"], b_text=b["text"], bbox_a=a["bbox"], bbox_b=b["bbox"], detail=dict(rotation=da)))
        elif abs(b["length"] / a["length"] - 1 if a["length"] else 0) <= cfg.barcode_scale_tol:  # a resize moves the centre; report the resize only
            d = _dist(a["bbox"], b["bbox"]) / MM
            if d > (cfg.barcode_shift_mm_raster if raster else cfg.barcode_shift_mm):
                dx = (_center(b["bbox"])[0] - _center(a["bbox"])[0]) / MM
                dy = (_center(b["bbox"])[1] - _center(a["bbox"])[1]) / MM
                out.append(Finding("barcode", "shifted", "major" if d >= 3 else "minor", page_no,
                                   f"Barcode {a['text']} moved {d:.1f} mm ({dx:+.1f} mm x, {dy:+.1f} mm y)",
                                   a_text=a["text"], b_text=b["text"], bbox_a=a["bbox"], bbox_b=b["bbox"], detail=dict(mm=d)))
        ratio = b["length"] / a["length"] if a["length"] else 1.0
        if abs(ratio - 1) > cfg.barcode_scale_tol:
            out.append(Finding("barcode", "scaled", "major", page_no,
                               f"Barcode {a['text']} is {abs(ratio - 1) * 100:.0f}% {'smaller' if ratio < 1 else 'larger'} than the reference (magnification affects scannability)",
                               a_text=a["text"], b_text=b["text"], bbox_a=a["bbox"], bbox_b=b["bbox"], detail=dict(ratio=ratio)))
    sample_raster = not pb.get_text("words")
    for a in ua:
        if sample_raster and raster:
            out.append(Finding("barcode", "missing", "major", page_no,
                               f"Barcode {a['text']} could not be read in the image-only sample. It may be printed but unscannable at this "
                               "resolution, or missing - check the artwork file or scan a printed proof",
                               a_text=a["text"], bbox_a=a["bbox"], confidence="medium"))
            continue
        out.append(Finding("barcode", "missing", "critical", page_no, f"Barcode {a['text']} is missing or unreadable in the sample",
                           a_text=a["text"], bbox_a=a["bbox"]))
    for b in ub:
        out.append(Finding("barcode", "added", "major", page_no, f"Sample has a barcode ({b['text']}) that is not in the reference",
                           b_text=b["text"], bbox_b=b["bbox"]))

    # print-quality: does the SAMPLE's barcode look scannable at all, independent of matching the
    # reference - a barcode can be unchanged in value/position/size and still fail because it's
    # printed with too little contrast, on too dark a background, or without a clear quiet zone
    for b0 in cb_own:
        b = dict(b0, bbox=align.map_rect(H, b0["bbox"])) if H is not None else b0
        q = _print_quality(img_b, b0["bbox"], cfg.dpi)
        if q["contrast"] < cfg.barcode_min_contrast:
            out.append(Finding("barcode", "low_contrast", "critical" if q["contrast"] < 0.3 else "major", page_no,
                               f"Barcode {b['text']} has too little print contrast to scan reliably ({q['contrast']:.0%} of full tonal range)",
                               b_text=b["text"], bbox_b=b["bbox"], detail=dict(contrast=q["contrast"])))
        elif q["max_reflectance"] < cfg.barcode_min_reflectance:
            out.append(Finding("barcode", "low_reflectance", "major", page_no,
                               f"Barcode {b['text']} sits on too dark a background to scan reliably (lightest tone in it is {q['max_reflectance']:.0%})",
                               b_text=b["text"], bbox_b=b["bbox"], detail=dict(max_reflectance=q["max_reflectance"])))
        if not _quiet_zone_ok(img_b, b0["bbox"], cfg.dpi, cfg.barcode_quiet_zone_mm):
            out.append(Finding("barcode", "quiet_zone_violation", "major", page_no,
                               f"Barcode {b['text']} doesn't have a clear {cfg.barcode_quiet_zone_mm:.0f} mm margin on both sides; "
                               "other print content that close can block a scanner's read",
                               b_text=b["text"], bbox_b=b["bbox"]))
    return out


def _caption_strip(img: np.ndarray, code: dict, dpi: float) -> tuple[np.ndarray, list]:
    k = dpi / 72
    x0, y0, x1, y1 = code["bbox"]
    box = _pad(code["bbox"], 14) if abs(code["angle"]) in (90.0, 270.0) else [x0 - 10, y0 - 2, x1 + 8, y1 + 16]
    xa, ya, xb, yb = (max(0, int(v * k)) for v in box)
    return img[ya:yb, xa:xb], [xa / k, ya / k, xb / k, yb / k]


def compare_fine_print(pa, img_a, img_b, page_no, cfg, explained_pt) -> list[Finding]:
    """Small numbers on a resampled image-only sample: the pixel check has to be tolerant there and can miss a
    changed digit in 4-6 pt text. For each small number in the reference's live text, OCR the same spot in the
    sample AND in a copy of the reference degraded to scan quality. Only when the degraded reference still reads
    correctly but the sample reads differently is it reported - so a plain OCR misread can't raise an alarm."""
    if not (cfg.ocr and ocr.available()):
        return []
    k = cfg.dpi / 72
    out: list[Finding] = []
    seen: dict[str, int] = {}
    for blk in pa.get_text("dict")["blocks"]:
        for ln in blk.get("lines", []):
            for sp in ln["spans"]:
                if sp["size"] >= 7 or not re.search(r"\d", sp["text"]):
                    continue
                for w in pa.get_text("words", clip=pymupdf.Rect(sp["bbox"])):
                    digits = re.sub(r"\D", "", w[4])
                    if not digits or any(_inter(list(w[:4]), e) > 0 for e in explained_pt):
                        continue
                    seen[w[4]] = seen.get(w[4], 0) + 1
                    if seen[w[4]] > 4 or len(seen) > 60:
                        continue  # repeated cells: a handful of each is enough, and keep the page fast
                    r = _pad(list(w[:4]), 1.2)
                    x0, y0, x1, y1 = (max(0, int(v * k)) for v in r)
                    ca, cb = img_a[y0:y1, x0:x1], img_b[y0:y1, x0:x1]
                    if ca.size == 0 or cb.size == 0:
                        continue
                    sm = cv2.resize(ca, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)  # ~150 dpi, like the scan
                    deg = cv2.resize(sm, (ca.shape[1], ca.shape[0]), interpolation=cv2.INTER_LINEAR)
                    up = lambda im: cv2.resize(im, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                    ra = re.sub(r"\D", "", ocr.read(up(deg), 0.3))
                    rb = re.sub(r"\D", "", ocr.read(up(cb), 0.3))
                    # same number of digits: a changed digit, not a partial read of a smudged word
                    if ra == digits and rb and len(rb) == len(digits) and rb != digits:
                        out.append(Finding("text", "fine_print_changed", "critical", page_no,
                                           f'Fine print differs (OCR): the reference says "{w[4]}" but the sample reads "{rb}" here '
                                           f"({sp['size']:.1f} pt text on a low-resolution image)",
                                           a_text=w[4], b_text=rb, bbox_a=list(w[:4]), bbox_b=list(w[:4]),
                                           detail=dict(ocr_reference_degraded=ra, ocr_sample=rb, size=sp["size"]), confidence="medium"))
    return out


def compare_captions(img_a, img_b, codes, page_no, cfg) -> list[Finding]:
    """The text printed beside a barcode is not covered by decoding the bars. On a resampled image-only copy
    the pixel check has to look away from the barcode (its bars alias), so read the caption with OCR on both
    sides and compare what it says."""
    if not (cfg.ocr and ocr.available()):
        return []
    out = []
    squash = lambda t: re.sub(r"[^0-9a-z]", "", t.casefold())
    for a in codes[0]:
        b = next((c for c in codes[1] if c["text"] == a["text"] and c["format"] == a["format"] and _dist(a["bbox"], c["bbox"]) < 15 * MM), None)
        if b is None:
            continue
        (ca, ra), (cb, rb) = _caption_strip(img_a, a, cfg.dpi), _caption_strip(img_b, b, cfg.dpi)
        ta, tb = squash(ocr.read(ca, 0.6)), squash(ocr.read(cb, 0.6))
        if ta and tb and ta != tb:
            out.append(Finding("barcode", "caption_changed", "critical" if re.search(r"\d", ta + tb) else "major", page_no,
                               f'Text printed beside barcode {a["text"]} differs (OCR): "{ta}" in the reference vs "{tb}" in the sample',
                               a_text=ta, b_text=tb, bbox_a=ra, bbox_b=rb, detail=dict(source="OCR"), confidence="medium"))
    return out


# ── 3. vector colour ─────────────────────────────────────────────────────
def _drawing_colors(page) -> list[dict]:
    """Fill/stroke colour of each vector shape, exactly as the PDF specifies it was painted -
    not sampled from the raster, so it isn't diluted by antialiasing or blur."""
    out = []
    for d in page.get_drawings():
        r = d.get("rect")
        if r is None or r.is_empty:
            continue
        fill = tuple(round(c * 255, 1) for c in d["fill"]) if d.get("fill") is not None else None
        stroke = tuple(round(c * 255, 1) for c in d["color"]) if d.get("color") is not None else None
        if fill is None and stroke is None:
            continue
        out.append(dict(rect=(r.x0, r.y0, r.x1, r.y1), fill=fill, stroke=stroke))
    return out


def _de_rgb(c1, c2) -> float:
    return float(np.linalg.norm(rgb2lab(np.array([[c1]], np.float32) / 255) - rgb2lab(np.array([[c2]], np.float32) / 255)))


def compare_colorants(pa, pb, page_no, H=None) -> list[Finding]:
    da, db = _drawing_colors(pa), _drawing_colors(pb)
    if H is not None:
        db = [dict(d, rect=tuple(align.map_rect(H, list(d["rect"])))) for d in db]
    out: list[Finding] = []
    used_b: set[int] = set()
    for a in da:
        best, best_iou = None, 0.6  # require a strong shape match, not just proximity, before comparing colour
        for j, b in enumerate(db):
            if j in used_b:
                continue
            i = _iou(a["rect"], b["rect"])
            if i > best_iou:
                best, best_iou = (j, b), i
        if best is None:
            continue
        j, b = best
        used_b.add(j)
        for key in ("fill", "stroke"):
            ca, cb = a[key], b[key]
            if ca is None or cb is None or ca == cb:
                continue
            de = _de_rgb(ca, cb)
            if de < 1.0:  # sub-1-ΔE float rounding from the extraction itself, not a real change
                continue
            rect = list(a["rect"])
            out.append(Finding("color", "colorant_changed", "major" if de >= 10 else "minor", page_no,
                               f"{'Fill' if key == 'fill' else 'Stroke'} colour value changed in the PDF itself "
                               f"(ΔE {de:.1f}): {_hex(ca)} → {_hex(cb)}",
                               bbox_a=rect, bbox_b=rect, detail=dict(delta_e=de, channel=key)))
    return _merge_nearby(out, page_no)


def _merge_nearby(findings: list[Finding], page_no: int, gap: float = 30.0) -> list[Finding]:
    """An icon drawn as several strokes (e.g. sun rays) recolours as several matched shapes, one
    finding each; collapse same-channel findings that sit next to each other into one."""
    if len(findings) <= 1:
        return findings
    out: list[Finding] = []
    for key in dict.fromkeys(f.detail.get("channel") for f in findings):  # first-seen order: a set would vary from run to run
        group = [f for f in findings if f.detail.get("channel") == key]
        for idx in _cluster(group, [f.bbox_a for f in group], lambda a, b: _dist(a, b) < gap):
            fs = [group[i] for i in idx]
            if len(fs) == 1:
                out.append(fs[0])
                continue
            rect = _union([f.bbox_a for f in fs])
            de = max(f.detail["delta_e"] for f in fs)
            sev = "major" if any(f.severity == "major" for f in fs) else "minor"
            out.append(Finding("color", "colorant_changed", sev, page_no,
                               f"{fs[0].message.split(' (ΔE')[0]} ({len(fs)} shapes, ΔE up to {de:.1f})",
                               bbox_a=rect, bbox_b=rect, detail=dict(delta_e=de, channel=key, count=len(fs))))
    return out


# ── 4. braille (English grade 1) ─────────────────────────────────────────
_DOT_POS = {1: (0, 0), 2: (0, 1), 3: (0, 2), 4: (1, 0), 5: (1, 1), 6: (1, 2)}
_POS_DOT = {v: k for k, v in _DOT_POS.items()}
_BRL_LETTERS = {
    (1,): "a", (1, 2): "b", (1, 4): "c", (1, 4, 5): "d", (1, 5): "e", (1, 2, 4): "f", (1, 2, 4, 5): "g",
    (1, 2, 5): "h", (2, 4): "i", (2, 4, 5): "j", (1, 3): "k", (1, 2, 3): "l", (1, 3, 4): "m", (1, 3, 4, 5): "n",
    (1, 3, 5): "o", (1, 2, 3, 4): "p", (1, 2, 3, 4, 5): "q", (1, 2, 3, 5): "r", (2, 3, 4): "s", (2, 3, 4, 5): "t",
    (1, 3, 6): "u", (1, 2, 3, 6): "v", (2, 4, 5, 6): "w", (1, 3, 4, 6): "x", (1, 3, 4, 5, 6): "y", (1, 3, 5, 6): "z",
}


def _braille_dots(page) -> list[tuple]:
    """Centres of small, dark, round filled shapes - what a braille dot looks like as a vector
    drawing. Works off the PDF's own paint commands, not a raster blob search. Restricted to
    circle-drawn shapes (bezier 'c' items) so it can't mistake barcode module squares (DataMatrix,
    QR - drawn as plain rectangles, 're') for braille."""
    out = []
    for d in page.get_drawings():
        if d.get("fill") is None:
            continue
        items = d.get("items") or []
        if not items or any(it[0] != "c" for it in items):
            continue
        r = d.get("rect")
        if r is None or r.is_empty:
            continue
        w, h = r.width, r.height
        if w <= 0 or h <= 0 or w > 5 or h > 5 or abs(w - h) > 0.6 * max(w, h):
            continue
        if sum(d["fill"]) / 3 > 0.35:
            continue
        out.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
    return out


def _point_cluster(pts: list[tuple], threshold: float) -> list[list[int]]:
    """Cluster points by Euclidean distance. _cluster()'s sweep prunes comparisons using the height
    of the rects it's given, so the rects here are padded well past `threshold` - a tight-fitting
    rect (e.g. near-zero for point data) would make the sweep silently skip valid same-cluster pairs."""
    rects = [(x - threshold, y - threshold, x + threshold, y + threshold) for x, y in pts]
    return _cluster(pts, rects, lambda a, b: _dist(a, b) < threshold)


def _decode_braille(dots: list[tuple]) -> list[tuple]:
    """[(bbox, decoded_text), ...] - one entry per contiguous run of braille dots on the page."""
    if len(dots) < 2:
        return []
    runs = _point_cluster(dots, 30)
    out = []
    for run in runs:
        pts = [dots[i] for i in run]
        if len(pts) < 2:
            continue
        p0 = min((math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) for i in range(len(pts)) for j in range(i + 1, len(pts))), default=0)
        if p0 <= 0:
            continue
        # a cell's own row-0 and row-2 dots can be 2*p0 apart - equal to or wider than the gap to the
        # NEXT cell's dots - so 2-D distance clustering can't reliably separate cells. Columns can:
        # dots in the same braille run share one baseline, so grouping x-coordinates into bands (two
        # per cell, p0 apart) then reading row from y - baseline is unambiguous regardless of which
        # of the 6 dot positions are actually present.
        y0 = min(y for _, y in pts)
        cell_bands: list[list[float]] = []
        for x in sorted(set(x for x, _ in pts)):
            if cell_bands and x - cell_bands[-1][-1] <= 1.4 * p0:
                cell_bands[-1].append(x)
            else:
                cell_bands.append([x])
        cell_info = []
        for band in cell_bands:
            col_of = {round(x, 3): min(i, 1) for i, x in enumerate(band)}
            dotnums = set()
            for px, py in pts:
                if round(px, 3) not in col_of:
                    continue
                row = round((py - y0) / p0)
                n = _POS_DOT.get((col_of[round(px, 3)], min(max(row, 0), 2)))
                if n:
                    dotnums.add(n)
            letter = _BRL_LETTERS.get(tuple(sorted(dotnums)), "?")
            cell_info.append((band[0], letter))
        cell_info.sort()
        out.append((_union([(x - 1, y - 1, x + 1, y + 1) for x, y in pts]), "".join(l for _, l in cell_info)))
    return out


def compare_braille(pa, pb, page_no) -> list[Finding]:
    ua, ub = _decode_braille(_braille_dots(pa)), _decode_braille(_braille_dots(pb))
    out: list[Finding] = []
    for a in list(ua):
        near = [b for b in ub if _dist(a[0], b[0]) < 20]
        match = min(near, key=lambda b: _dist(a[0], b[0])) if near else None
        if match is not None:
            ua.remove(a); ub.remove(match)
            if a[1] != match[1]:
                out.append(Finding("braille", "text_changed", "critical", page_no,
                                   f'Braille reads "{a[1]}" in the reference but "{match[1]}" in the sample',
                                   a_text=a[1], b_text=match[1], bbox_a=list(a[0]), bbox_b=list(match[0]),
                                   detail=dict(decoded_a=a[1], decoded_b=match[1])))
    for a in ua:
        out.append(Finding("braille", "removed", "critical", page_no, f'Braille reading "{a[1]}" is missing from the sample',
                           a_text=a[1], bbox_a=list(a[0])))
    for b in ub:
        out.append(Finding("braille", "added", "major", page_no, f'Sample has braille reading "{b[1]}" not present in the reference',
                           b_text=b[1], bbox_b=list(b[0])))
    return out


# ── 5. layers (OCG) ───────────────────────────────────────────────────────
def _layer_region(page, name):
    rects = [(r.x0, r.y0, r.x1, r.y1) for d in page.get_drawings() if d.get("layer") == name for r in [d.get("rect")] if r and not r.is_empty]
    return _union(rects)


def compare_layers(A, B, pa, pb, page_no) -> list[Finding]:
    """Optional-content-group (spot-finish / varnish / packaging-panel layer) definitions, read
    directly from each PDF's structure rather than inferred from what happened to be visible when
    rendered. The bbox (where available) is the union of this page's content tagged with that layer,
    so it can be matched to the same ground-truth region a pixel-only check would also land on."""
    la = {c["text"]: bool(c["on"]) for c in A.layer_ui_configs()}
    lb = {c["text"]: bool(c["on"]) for c in B.layer_ui_configs()}
    out: list[Finding] = []
    for name in sorted(set(la) - set(lb)):
        r = _layer_region(pa, name)
        out.append(Finding("layer", "removed", "major", page_no, f"Layer '{name}' removed from the sample (was {'on' if la[name] else 'off'} by default)", bbox_a=r))
    for name in sorted(set(lb) - set(la)):
        r = _layer_region(pb, name)
        out.append(Finding("layer", "added", "major", page_no, f"Sample has a layer '{name}' not present in the reference", bbox_b=r))
    for name in sorted(set(la) & set(lb)):
        if la[name] != lb[name]:
            r = _union([x for x in (_layer_region(pa, name), _layer_region(pb, name)) if x])
            out.append(Finding("layer", "visibility_changed", "major", page_no,
                               f"Layer '{name}' default visibility changed: {'on' if la[name] else 'off'} → {'on' if lb[name] else 'off'}",
                               bbox_a=r, bbox_b=r, detail=dict(before=la[name], after=lb[name])))
    return out


# ── 6. visual ─────────────────────────────────────────────────────────────
def _render(page, dpi) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csRGB)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3).copy()


def _canvas(a, b):
    h, w = max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])
    out = []
    for im in (a, b):
        c = np.full((h, w, 3), 255, np.uint8)
        c[: im.shape[0], : im.shape[1]] = im
        out.append(c)
    return out


def _mode_color(crop):
    q = (crop.reshape(-1, 3) // 8).astype(np.int32)
    key = q[:, 0] * 1024 + q[:, 1] * 32 + q[:, 2]
    m = np.bincount(key).argmax()
    return np.array([(m // 1024) * 8 + 4, ((m // 32) % 32) * 8 + 4, (m % 32) * 8 + 4], np.float32)


def _hex(c):
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, v))) for v in c)


def _ink(crop, bg):
    return int((np.linalg.norm(crop.astype(np.float32) - bg, axis=-1) > 40).sum())


def _edge_sim(ca, cb):
    ea = cv2.Canny(cv2.cvtColor(ca, cv2.COLOR_RGB2GRAY), 60, 160) > 0
    eb = cv2.Canny(cv2.cvtColor(cb, cv2.COLOR_RGB2GRAY), 60, 160) > 0
    k = np.ones((3, 3), np.uint8)
    da, db = cv2.dilate(ea.astype(np.uint8), k) > 0, cv2.dilate(eb.astype(np.uint8), k) > 0
    union = int(ea.sum() + eb.sum())
    return 1.0 if union == 0 else (int((ea & db).sum()) + int((eb & da).sum())) / union


def _find_shift(ga, gb, box, search_px):
    x0, y0, x1, y1 = box
    pad = 4
    tx0, ty0 = max(0, x0 - pad), max(0, y0 - pad)
    tx1, ty1 = min(ga.shape[1], x1 + pad), min(ga.shape[0], y1 + pad)
    tpl = ga[ty0:ty1, tx0:tx1]
    if tpl.size == 0 or float(tpl.std()) < 12:
        return None
    sx0, sy0 = max(0, tx0 - search_px), max(0, ty0 - search_px)
    sx1, sy1 = min(gb.shape[1], tx1 + search_px), min(gb.shape[0], ty1 + search_px)
    win = gb[sy0:sy1, sx0:sx1]
    if win.shape[0] < tpl.shape[0] or win.shape[1] < tpl.shape[1]:
        return None
    res = cv2.matchTemplate(win, tpl, cv2.TM_CCOEFF_NORMED)
    _mn, mx, _l, loc = cv2.minMaxLoc(res)
    return mx, sx0 + loc[0] - tx0, sy0 + loc[1] - ty0, (sx0 + loc[0], sy0 + loc[1], sx0 + loc[0] + tpl.shape[1], sy0 + loc[1] + tpl.shape[0])


def _pair_noise(a: np.ndarray, b: np.ndarray, tile: int = 48) -> float:
    """How far apart do two renders of supposedly the SAME artwork sit, measured where there is ink?
    Upper-quartile of per-tile mean absolute grey difference. Defects touch a few tiles, so the 75th
    percentile reflects resampling noise, not the defects. 0 means pixel-identical wherever nothing
    changed (e.g. a flattened copy at the same dpi); 20-60 means the copy was resampled."""
    ga, gb = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY), cv2.cvtColor(b, cv2.COLOR_RGB2GRAY)  # 8-bit: differences of whole grey levels are exact either way
    ink = ((ga < 200) | (gb < 200)).astype(np.float32)
    h, w = ga.shape[0] // tile, ga.shape[1] // tile
    if h < 1 or w < 1:
        return 99.0
    rs = lambda x: cv2.resize(x, (w, h), interpolation=cv2.INTER_AREA)
    den = rs(ink)
    vals = (rs(cv2.absdiff(ga, gb).astype(np.float32) * ink) / np.maximum(den, 1e-6))[den > 0.02]
    return float(np.percentile(vals, 75)) if vals.size else 0.0


def _move_residual(ga, gb, box, m) -> tuple[float, int]:
    """After sliding the sample's copy back onto the reference, how much of the artwork still disagrees?
    A template score of 0.9 tolerates one changed digit in a short line, so 'it matches at the new
    position' alone can't prove the CONTENT is identical. Real moves leave a residual near 0 (<=0.03);
    a one-character edit leaves ~0.15."""
    x0, y0, x1, y1 = box
    pad = 4
    tx0, ty0 = max(0, x0 - pad), max(0, y0 - pad)
    tx1, ty1 = min(ga.shape[1], x1 + pad), min(ga.shape[0], y1 + pad)
    dx, dy = m[1], m[2]
    if ty0 + dy < 0 or tx0 + dx < 0:
        return 1.0, 10 ** 6
    tpl = cv2.GaussianBlur(ga[ty0:ty1, tx0:tx1], (0, 0), 1.0).astype(np.int16)
    win = cv2.GaussianBlur(gb, (0, 0), 1.0)[ty0 + dy:ty1 + dy, tx0 + dx:tx1 + dx].astype(np.int16)
    if win.shape != tpl.shape or tpl.size == 0:
        return 1.0, 10 ** 6
    ink = (tpl < 160) | (win < 160)
    n = int((np.abs(tpl - win) > 60).sum())
    return n / max(1, int(ink.sum())), n


def _already_there(ga, box, m, cfg) -> bool:
    """True when the reference already contains this same artwork at the destination - a repeated cell,
    a step-and-repeat label, a duplicated logo. The template 'moved' there only because an identical
    neighbour exists, so it is not evidence that anything moved."""
    x0, y0, x1, y1 = box
    pad = 4
    tx0, ty0 = max(0, x0 - pad), max(0, y0 - pad)
    tx1, ty1 = min(ga.shape[1], x1 + pad), min(ga.shape[0], y1 + pad)
    dx, dy = m[1], m[2]
    if ty0 + dy < 0 or tx0 + dx < 0:
        return False
    tpl = cv2.GaussianBlur(ga[ty0:ty1, tx0:tx1], (0, 0), 1.0).astype(np.int16)
    there = cv2.GaussianBlur(ga, (0, 0), 1.0)[ty0 + dy:ty1 + dy, tx0 + dx:tx1 + dx].astype(np.int16)
    if there.shape != tpl.shape or tpl.size == 0:
        return False
    ink = (tpl < 160) | (there < 160)
    return (np.abs(tpl - there) > 60).sum() / max(1, int(ink.sum())) <= cfg.move_max_residual


def _clean_move(res: tuple[float, int], cfg: Config) -> bool:
    ratio, n = res
    return ratio <= cfg.move_max_residual and not (n > 12 and ratio > 0.015)


def _styles(page, rect_pt, k: float = 1.0):
    """(size, font) of the text in a rect. k rescales sizes, so a sample printed at 98.5% compares as unscaled."""
    out = set()
    for blk in page.get_text("dict", clip=pymupdf.Rect(*rect_pt))["blocks"]:
        for ln in blk.get("lines", []):
            for sp in ln["spans"]:
                if sp["text"].strip():
                    out.add((round(sp["size"] * k, 1), sp["font"]))
    return out


def compare_visual(img_a, img_b, pa, pb, page_no, explained_pt, cfg, raster, noise=None, Hinv=None, size_k: float = 1.0, registered=False) -> tuple[list[Finding], np.ndarray, dict]:
    k = cfg.dpi / 72
    text_page = pa if pa.get_text("words") else (pb if pb.get_text("words") else None)
    a, b = _canvas(img_a, img_b)
    de_raw = lab_dist(a, b)
    if noise is None:
        noise = _pair_noise(a, b) if raster else 0.0
    # same pixel grid, not merely similar - a registered page was resampled by a sub-pixel offset, so never 'aligned'
    aligned = raster and noise < 1.0 and img_a.shape == img_b.shape and not registered
    if aligned:
        # both files share a pixel grid (e.g. a same-dpi flatten): there is no resampling noise to hide from,
        # so use the full-sensitivity comparison, not the blurred one. This is what catches 4 pt text.
        de = de_raw
        mask = (de > cfg.delta_e).astype(np.uint8)
    elif raster:
        ab = cv2.GaussianBlur(a, (0, 0), cfg.raster_blur)
        bb = cv2.GaussianBlur(b, (0, 0), cfg.raster_blur)
        de_blur = lab_dist(ab, bb)
        # resampling noise from two independent rasterisations shows up wherever the artwork has fine
        # detail - hard edges, but just as much halftone patterns (QR/DataMatrix modules) or photo
        # texture (a continuous-tone illustration); a genuinely FLAT region (solid fill, no local
        # texture in either render) can't drift between two renders of the same artwork, so a much
        # tighter threshold is safe there and catches solid-fill colour shifts the loose,
        # texture-safe threshold alone would miss (e.g. a subtle ΔE~5 recolour of an icon or band).
        # "flat" is measured directly as local variance, not inferred from edge detection, so it
        # isn't fooled by soft photo gradients or dense small patterns that have no hard edge at all.
        gray = cv2.cvtColor(((a.astype(np.int16) + b.astype(np.int16)) // 2).astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
        win = max(3, 2 * int(3 * cfg.raster_blur) + 1)
        mean = cv2.blur(gray, (win, win))
        local_var = cv2.blur(gray * gray, (win, win)) - mean * mean
        flat = local_var < cfg.raster_flat_var
        mask = np.where(flat, de_raw > cfg.raster_delta_e_tight, de_blur > cfg.raster_delta_e).astype(np.uint8)
        de = de_raw
    else:
        de = de_raw
        mask = (de > cfg.delta_e).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= cfg.min_area_px
    mask = keep[lab].astype(np.uint8)
    r = int(cfg.merge_mm * MM * k)
    grown = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(grown, connectivity=8)
    boxes = []
    for i in range(1, n):
        x, y, w, h = (int(stats[i, c]) for c in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        boxes.append([x, y, x + w, y + h])
    # a ring with something nested inside it is one element, not two: merge any regions that overlap
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if _inter(boxes[i], boxes[j]) > 0:
                    boxes[i] = _union([boxes[i], boxes[j]])
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    boxes = sorted((tuple(int(v) for v in b) for b in boxes), key=lambda t: (t[1], t[0]))

    ga, gb = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY), cv2.cvtColor(b, cv2.COLOR_RGB2GRAY)
    expl_px = [_pad([v * k for v in e], 4 * k) for e in explained_pt]

    def explained(bx):
        ar = _area(bx)
        return ar > 0 and any(_inter(bx, e) / ar >= 0.4 for e in expl_px)

    todo = [bx for bx in boxes if not explained(bx)]
    search = int(cfg.move_search_mm * MM * k)
    moves, consumed, handled = [], [], set()
    for bx in todo:
        m = _find_shift(ga, gb, bx, search)
        if m and m[0] >= 0.9 and math.hypot(m[1], m[2]) / k / MM > cfg.move_tol_mm and _clean_move(_move_residual(ga, gb, bx, m), cfg) and not _already_there(ga, bx, m, cfg):
            moves.append((bx, m)); consumed.append(m[3]); handled.add(bx)
    for bx in todo:
        if bx in handled:
            continue
        ar = _area(bx)
        if any(_inter(bx, c) / ar >= 0.5 for c in consumed):
            handled.add(bx)

    out: list[Finding] = []
    to_pt = lambda bx: [v / k for v in bx]
    # elements that moved by the same amount and sit next to each other are one block that moved
    groups: list[list] = []
    for bx, (score, dx, dy, dest) in moves:
        dxm, dym = dx / k / MM, dy / k / MM
        for g in groups:
            if abs(g["dx"] - dxm) <= 0.3 and abs(g["dy"] - dym) <= 0.3 and any(
                    _inter(_pad(to_pt(bx), 8 * MM), to_pt(o)) > 0 for o in g["boxes"]):
                g["boxes"].append(bx); g["dests"].append(dest)
                break
        else:
            groups.append(dict(dx=dxm, dy=dym, boxes=[bx], dests=[dest], score=score))
    for g in groups:
        dist = math.hypot(g["dx"], g["dy"])
        n_el = len(g["boxes"])
        what = "Element" if n_el == 1 else f"Block of {n_el} elements"
        out.append(Finding("layout", "moved", "minor" if dist < 2 else "major", page_no,
                           f"{what} moved {dist:.1f} mm ({g['dx']:+.1f} mm x, {g['dy']:+.1f} mm y); content identical",
                           bbox_a=_union([to_pt(b) for b in g["boxes"]]), bbox_b=_union([to_pt(d) for d in g["dests"]]),
                           detail=dict(dx_mm=g["dx"], dy_mm=g["dy"], match=float(g["score"]), elements=n_el)))

    stats_out = dict(regions=len(todo), noise=noise, aligned=aligned, ocr_regions=0, ocr_available=bool(cfg.ocr and ocr.available()))
    for bx in todo:
        if bx in handled:
            continue
        x0, y0, x1, y1 = bx
        ca, cb = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
        rect = to_pt(bx)
        changed = mask[y0:y1, x0:x1] > 0
        mean_de = float(de[y0:y1, x0:x1][changed].mean()) if changed.any() else 0.0
        area_mm2 = _area(rect) / (MM * MM)

        rect_b = align.map_rect(Hinv, rect) if Hinv is not None else rect
        sa, sb = _styles(pa, rect), _styles(pb, rect_b, size_k)
        if sa and sb and sa != sb:
            out.append(Finding("format", "text_style", "minor", page_no,
                               "Text style changed: " + ", ".join(f"{s} pt {f}" for s, f in sorted(sa)) + " → " + ", ".join(f"{s} pt {f}" for s, f in sorted(sb)) + " (wording unchanged)",
                               bbox_a=rect, bbox_b=rect, detail=dict(before=sorted(sa), after=sorted(sb))))
            continue

        if not raster and _edge_sim(ca, cb) >= 0.9:
            out.append(Finding("color", "color_shift", "major" if mean_de >= 10 else "minor", page_no,
                               f"Colour changed (ΔE ≈ {mean_de:.1f}): {_hex(np.median(ca[changed], axis=0))} → {_hex(np.median(cb[changed], axis=0))}",
                               bbox_a=rect, bbox_b=rect, detail=dict(delta_e=mean_de)))
            continue

        ia, ib = _ink(ca, _mode_color(ca)), _ink(cb, _mode_color(cb))
        if ib <= 0.1 * ia:
            kind, msg = "removed", "Graphic element missing from sample"
        elif ia <= 0.1 * ib:
            kind, msg = "added", "Extra graphic element in sample"
        else:
            kind, msg = "changed", "Visual content differs (text/graphics not explained by a text or barcode change)"
        msg, sev, ref_txt = f"{msg} ({area_mm2:.1f} mm²)", ("minor" if area_mm2 < 2.0 else "major"), ""
        if raster and text_page is not None:
            # one file is image-only: show what the live-text file says here, and treat digits as critical
            clip = align.map_rect(Hinv, rect) if (Hinv is not None and text_page is pb) else rect
            ref_txt = " ".join(w[4] for w in text_page.get_text("words", clip=pymupdf.Rect(*clip)))
            if ref_txt:
                msg += f'; live text in the {"reference" if text_page is pa else "sample"} at this spot: "{ref_txt}"'
                if re.search(r"\d", ref_txt):
                    sev = "critical"
        det = dict(area_mm2=area_mm2)
        a_txt, b_txt = ref_txt if text_page is pa else "", ref_txt if text_page is pb else ""
        if stats_out["ocr_available"] and stats_out["ocr_regions"] < cfg.ocr_max_regions:
            # what does each side actually SAY in this spot? Read with OCR (never a language model) and let
            # a changed digit raise the severity: a pixel diff alone can't tell a stray mark from a wrong dose.
            pad, padx = int(1.5 * MM * k), int(4 * MM * k)  # wider sideways so a unit next to a number is read too
            px0, py0, px1, py1 = max(0, x0 - padx), max(0, y0 - pad), min(a.shape[1], x1 + padx), min(a.shape[0], y1 + pad)
            oa, ob = ocr.read(a[py0:py1, px0:px1]), ocr.read(b[py0:py1, px0:px1])
            stats_out["ocr_regions"] += 1
            det.update(ocr_a=oa, ocr_b=ob)
            squash = lambda t: re.sub(r"\s+", "", t).casefold()
            if squash(oa) != squash(ob):
                # lead with what the text actually says; the pixel measurements stay in the explanation
                msg = f'Text reads differently (OCR): "{oa}" in the reference vs "{ob}" in the sample ({area_mm2:.1f} mm²)'
                a_txt, b_txt = oa, ob
                if re.search(r"\d", oa + ob) or any(UNITS.match(t) for t in (oa + " " + ob).split()):
                    sev = "critical"
                elif sev == "minor":
                    sev = "major"  # the words themselves differ, not just some pixels
        out.append(Finding("graphic", kind, sev, page_no, msg, a_text=a_txt, b_text=b_txt,
                           bbox_a=rect, bbox_b=rect, detail=det, confidence="medium" if raster else "high"))
    return out, mask, stats_out


# ── 6b. ink separations (CMYK plates) ─────────────────────────────────────
def _cmyk(page, dpi: int) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csCMYK, alpha=False)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 4)


def _pct(v) -> str:
    return "/".join(f"{x * 100 / 255:.0f}" for x in v)


def compare_separations(pa, pb, page_no, cfg, H=None) -> list[Finding]:
    """Render both pages to CMYK and compare each ink plate (cyan, magenta, yellow, black) on its own. This sees
    what a screen (RGB) comparison can't: a K-only black rebuilt as rich black, a colour rebuilt from different
    inks, a plate that went missing - all of which can look identical on screen and print differently."""
    dpi = cfg.separation_dpi
    ca, cb = _cmyk(pa, dpi), _cmyk(pb, dpi)
    if H is not None:
        cb = align.render_aligned(pb, H, ca.shape, dpi, colorspace=pymupdf.csCMYK, border=0)
    if ca.shape != cb.shape:
        return []
    if H is not None:  # resampled: compare smoothed plates so interpolation at edges and in photos isn't a "change"
        ca = cv2.GaussianBlur(ca, (0, 0), 1.5)
        cb = cv2.GaussianBlur(cb, (0, 0), 1.5)
    d = np.abs(ca.astype(np.int16) - cb.astype(np.int16))
    mask = (d.max(axis=2) > cfg.separation_tol * 255 / 100).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(mask, np.ones((5, 5), np.uint8)), connectivity=8)
    k = 72 / dpi
    out: list[Finding] = []
    for i in range(1, n):
        x, y, w, h, area = (int(stats[i, c]) for c in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT, cv2.CC_STAT_AREA))
        sel = (lab[y:y + h, x:x + w] == i) & (mask[y:y + h, x:x + w] > 0)
        if sel.sum() < (12 if H is None else 60):
            continue
        ink_a = ca[y:y + h, x:x + w].astype(np.int16).sum(axis=2) > 60
        ink_b = cb[y:y + h, x:x + w].astype(np.int16).sum(axis=2) > 60
        union = (ink_a | ink_b).sum()
        if union and (ink_a & ink_b).sum() / union < 0.9:
            continue  # the artwork itself changed shape here (bolder text, removed picture): not an ink-build change
        va = np.median(ca[y:y + h, x:x + w][sel], axis=0)
        vb = np.median(cb[y:y + h, x:x + w][sel], axis=0)
        names = [c for c, a_, b_ in zip("CMYK", va, vb) if abs(int(a_) - int(b_)) > cfg.separation_tol * 255 / 100]
        if not names:
            continue
        rich = va[3] > 240 and vb[3] > 240 and abs(int(va[:3].sum()) - int(vb[:3].sum())) > 60
        what = ("black build changed (" + ("K-only black became rich black" if vb[:3].sum() > va[:3].sum() else "rich black became K-only black")
                + "): looks the same on screen, prints differently - fine text in rich black risks misregistration") if rich \
            else f"{', '.join({'C': 'cyan', 'M': 'magenta', 'Y': 'yellow', 'K': 'black'}[c] for c in names)} plate changed"
        rect = [x * k, y * k, (x + w) * k, (y + h) * k]
        if H is not None and any(_inter(rect, _pad(list(im["bbox"]), 2)) > 0.3 * _area(rect) for im in pa.get_image_info()):
            continue  # a placed picture resampled by the realignment; picture content is the visual check's job
        out.append(Finding("color", "separation_changed", "major", page_no,
                           f"Ink separations differ, {what}: CMYK {_pct(va)} → {_pct(vb)} %",
                           bbox_a=rect, bbox_b=rect, detail=dict(cmyk_a=[round(float(v) * 100 / 255) for v in va],
                                                                  cmyk_b=[round(float(v) * 100 / 255) for v in vb], plates=names, rich_black=rich)))
    return out


# ── 7. structure (page boxes, rotation, fonts, image resolution) ─────────
def _box_wh(r):
    return (r.width, r.height)


def compare_structure(pa, pb, page_no, cfg, raster=False, H=None) -> list[Finding]:
    """Things a print shop cares about that a rendered picture can't show: the trim/bleed geometry the
    die-line is cut to, page rotation, fonts that aren't embedded, and images whose effective resolution
    dropped (a re-export that quietly downsampled the artwork)."""
    out: list[Finding] = []
    if pa.rotation != pb.rotation:
        out.append(Finding("structure", "page_rotation", "major", page_no, f"Page rotation differs: {pa.rotation}° → {pb.rotation}°"))
    # a flattened / re-rasterised copy never carries the original's trim and bleed boxes, so those can only
    # be compared between two live files; the media box (page size) is compared either way
    # (the media box is the page size, already reported by the driver as page_size)
    boxes = () if raster else (("TrimBox", pa.trimbox, pb.trimbox), ("BleedBox", pa.bleedbox, pb.bleedbox))
    for label, ba, bb in boxes:
        (wa, ha), (wb, hb) = _box_wh(ba), _box_wh(bb)
        if abs(wa - wb) > cfg.size_tol_pt or abs(ha - hb) > cfg.size_tol_pt:
            out.append(Finding("structure", "page_box", "major", page_no,
                               f"{label} differs: {wa / MM:.1f} x {ha / MM:.1f} mm → {wb / MM:.1f} x {hb / MM:.1f} mm "
                               "(the die-line / cutting geometry is defined here)"))

    def unembedded(page):
        return {f[3] for f in page.get_fonts() if f[1] == "n/a"}
    new = sorted(unembedded(pb) - unembedded(pa))
    if new:
        out.append(Finding("structure", "font_not_embedded", "minor", page_no,
                           f"Sample uses font(s) that are not embedded: {', '.join(new)} - they will be substituted by whatever the printer or viewer has",
                           b_text=", ".join(new), detail=dict(fonts=new)))

    def images(page):
        res = []
        for im in page.get_image_info():
            bb = im["bbox"]
            w_in = (bb[2] - bb[0]) / 72
            if w_in > 0.05 and im.get("width"):
                res.append((list(bb), im["width"] / w_in))
        return res
    ia, ib, used = images(pa), images(pb), set()
    if H is not None:
        ib = [(align.map_rect(H, bb), ppi) for bb, ppi in ib]
    for bbox_a, ppi_a in ia:
        best = max(((_iou(bbox_a, bbox_b), j) for j, (bbox_b, _p) in enumerate(ib) if j not in used), default=(0, None))
        if best[0] < 0.6:
            continue
        used.add(best[1])
        bbox_b, ppi_b = ib[best[1]]
        if ppi_b < ppi_a * cfg.image_ppi_drop and ppi_b < 300:
            out.append(Finding("structure", "image_resolution", "major" if ppi_b < 150 else "minor", page_no,
                               f"Image effective resolution dropped from {ppi_a:.0f} ppi to {ppi_b:.0f} ppi (may print soft or pixelated)",
                               bbox_a=bbox_a, bbox_b=bbox_b, detail=dict(ppi_a=ppi_a, ppi_b=ppi_b)))
    return out


def _tiny_text(page, limit: float = 6.0) -> int:
    """Number of text spans set smaller than `limit` pt (fine print: lot/expiry lines, legal text)."""
    n = 0
    for blk in page.get_text("dict")["blocks"]:
        for ln in blk.get("lines", []):
            for sp in ln["spans"]:
                if sp["text"].strip() and sp["size"] < limit:
                    n += 1
    return n


_REF = re.compile(r"(\d+) 0 R")
_SEP = re.compile(r"/Separation\s*/([^\s/\[\]<>()]+)")
_DEVN = re.compile(r"/DeviceN\s*\[([^\]]*)\]")


def _inks(page) -> tuple[set, dict]:
    """Spot colours (Separation / DeviceN names) and overprint settings reachable from a page's resources,
    read from the PDF objects themselves - these never show up in an RGB render."""
    doc = page.parent
    typ, val = doc.xref_get_key(page.xref, "Resources")
    todo = [int(x) for x in _REF.findall(val)] if typ == "xref" else []
    text = [val] if typ == "dict" else []
    todo += [int(x) for x in _REF.findall(val)] if typ == "dict" else []
    seen: set[int] = set()
    while todo and len(seen) < 4000:
        x = todo.pop()
        if x in seen or x <= 0 or x >= doc.xref_length():
            continue
        seen.add(x)
        try:
            o = doc.xref_object(x, compressed=True)
        except Exception:
            continue
        if "/Type/Page" in o.replace(" ", "") and "/Pages" not in o:
            continue
        text.append(o)
        todo += [int(r) for r in _REF.findall(o)]
    blob = chr(10).join(text)
    dec = lambda n: re.sub(r"#([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), n)
    spots = {dec(n) for n in _SEP.findall(blob)} | {dec(n) for grp in _DEVN.findall(blob) for n in re.findall(r"/([^\s/]+)", grp)}
    spots -= {"All", "None", "Cyan", "Magenta", "Yellow", "Black"}
    op = dict(on=len(re.findall(r"/OP\s*true", blob)) + len(re.findall(r"/op\s*true", blob)),
              off=len(re.findall(r"/OP\s*false", blob)) + len(re.findall(r"/op\s*false", blob)))
    return spots, op


def compare_inks(pa, pb, page_no) -> list[Finding]:
    (sa, oa), (sb, ob) = _inks(pa), _inks(pb)
    out: list[Finding] = []
    gone, new = sorted(sa - sb), sorted(sb - sa)
    if len(gone) == 1 and len(new) == 1:
        out.append(Finding("color", "spot_replaced", "major", page_no, f"Spot colour {gone[0]} was replaced by {new[0]} (a different ink on press)",
                           a_text=gone[0], b_text=new[0], detail=dict(spots_a=sorted(sa), spots_b=sorted(sb))))
    else:
        for g in gone:
            out.append(Finding("color", "spot_removed", "major", page_no, f"Spot colour {g} is no longer used in the sample", a_text=g,
                               detail=dict(spots_a=sorted(sa), spots_b=sorted(sb))))
        for n in new:
            out.append(Finding("color", "spot_added", "major", page_no, f"Sample uses a spot colour that the reference doesn't: {n}", b_text=n,
                               detail=dict(spots_a=sorted(sa), spots_b=sorted(sb))))
    if bool(oa["on"]) != bool(ob["on"]):
        out.append(Finding("color", "overprint_changed", "major", page_no,
                           f"Overprint {'switched on' if ob['on'] else 'switched off'} in the sample - objects will "
                           + ("print on top of the colours beneath instead of knocking them out" if ob["on"] else "knock out the colours beneath instead of overprinting them")
                           + "; invisible on screen, visible on press", detail=dict(op_a=oa, op_b=ob)))
    return out


def _page_text(page) -> str:
    return " ".join(w[4] for w in page.get_text("words"))[:2500]


def _thumb(page) -> np.ndarray:
    pix = page.get_pixmap(dpi=12, alpha=False, colorspace=pymupdf.csGRAY)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w)
    return cv2.resize(im, (24, 32), interpolation=cv2.INTER_AREA).astype(np.float32)


def _page_sim(pa, pb) -> float:
    ta, tb = _page_text(pa), _page_text(pb)
    if ta and tb:
        sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
        return sm.ratio() if sm.real_quick_ratio() > 0.2 else 0.0
    if ta or tb:
        return 0.0
    return float(1 - np.abs(_thumb(pa) - _thumb(pb)).mean() / 255)


def _align_pages(A, B, cfg):
    """Pair pages of the two files. Same page count -> by position. Different counts -> monotonic
    best-similarity alignment, so one inserted or deleted page doesn't shift (and so mis-compare) every
    page after it. Returns (pairs, unmatched_reference, unmatched_sample)."""
    na, nb = len(A), len(B)
    if na == nb and 1 < na <= 80:
        # same count: normally page i <-> page i, unless the pages were re-ordered. Only pay for the full
        # similarity matrix when some page doesn't resemble its same-position partner.
        diag = [_page_sim(A[i], B[i]) for i in range(na)]
        if min(diag) < 0.5:
            from scipy.optimize import linear_sum_assignment
            sim = np.array([[diag[i] if i == j else _page_sim(A[i], B[j]) for j in range(nb)] for i in range(na)])
            ri, ci = linear_sum_assignment(-sim)
            if sim[ri, ci].sum() > sum(diag) + 0.3:
                return [(int(i), int(j)) for i, j in zip(ri, ci)], [], []
        return [(i, i) for i in range(na)], [], []
    if na == nb or max(na, nb) > 80:
        n = min(na, nb)
        return [(i, i) for i in range(n)], list(range(n, na)), list(range(n, nb))
    sim = [[_page_sim(A[i], B[j]) for j in range(nb)] for i in range(na)]
    best = [[0.0] * (nb + 1) for _ in range(na + 1)]
    for i in range(1, na + 1):
        for j in range(1, nb + 1):
            v = sim[i - 1][j - 1]
            best[i][j] = max(best[i - 1][j], best[i][j - 1], best[i - 1][j - 1] + v if v >= cfg.page_align_min_sim else 0)
    pairs, i, j = [], na, nb
    while i > 0 and j > 0:
        v = sim[i - 1][j - 1]
        if v >= cfg.page_align_min_sim and abs(best[i][j] - (best[i - 1][j - 1] + v)) < 1e-9:
            pairs.append((i - 1, j - 1)); i -= 1; j -= 1
        elif best[i][j] == best[i - 1][j]:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    ma, mb = {p[0] for p in pairs}, {p[1] for p in pairs}
    return pairs, [x for x in range(na) if x not in ma], [x for x in range(nb) if x not in mb]


def _merge_confirmations(findings: list[Finding]) -> list[Finding]:
    """A copy-deck finding at the same spot as a text / graphic finding describes the same problem, found a second,
    independent way. Keep one finding, say it was confirmed by the approved text, and keep the higher severity."""
    squash = lambda t: re.sub(r"\W+", "", (t or "").casefold())
    keep = []
    for f in findings:
        if f.category == "copydeck" and f.kind in ("missing", "not_in_deck") and not (f.kind == "missing" and f.bbox_b):
            # a whole approved line reported missing / unexpected, when the reference comparison already reports an
            # edit inside that same line, is that edit seen from the other side
            line = squash(f.a_text or f.b_text)
            host = next((h for h in findings if h is not f and h.category in ("text", "graphic") and h.page == f.page
                         and ((h.a_text and squash(h.a_text) in line) or (h.b_text and squash(h.b_text) in line))
                         and (f.kind == "missing" or (f.bbox_b and any(r and _inter(_pad(r, 2), f.bbox_b) > 0 for r in (h.bbox_b, h.bbox_a))))), None)
            if host is not None:
                if "approved_text" not in host.detail:
                    host.message += " - also confirmed against the approved text"
                host.detail.setdefault("approved_text", f.message)
                continue
        if f.category == "copydeck" and f.kind == "text_changed" and f.bbox_b:
            host = next((h for h in findings if h is not f and h.category in ("text", "graphic", "barcode", "layout") and h.page == f.page
                         and any(r and _inter(_pad(r, 2), f.bbox_b) > 0 for r in (h.bbox_b, h.bbox_a))
                         and (h.category == "layout" or not f.b_text or squash(f.b_text) in squash(h.b_text + " " + h.message) or squash(h.b_text) in squash(f.b_text))), None)
            if host is not None:
                if "approved_text" not in host.detail:
                    host.message += " - also confirmed against the approved text"
                host.detail.setdefault("approved_text", f.message)
                # a word that moved leaves approved-text gaps behind it; those don't make the move more serious
                if host.category != "layout" and SEV_RANK[f.severity] > SEV_RANK[host.severity]:
                    host.severity = f.severity
                continue
        keep.append(f)
    return keep


def _spelling(A, B, pairs, findings, deck_paras, coverage, page_H=None) -> list[Finding]:
    """New unknown words in the sample become findings (or annotate an existing text finding at the same spot);
    unknown words the approved reference already had are only listed in the coverage report."""
    from . import spelling
    if not spelling.available():
        for c in coverage:
            c["checks"].append(dict(name="Spelling", status="skipped", note="dictionary package not installed"))
        return []
    pw = spelling.product_words()
    vocab = set(pw)
    for page in A:
        vocab |= {w.casefold() for w in spelling.words(page.get_text())}
    for t in deck_paras:
        vocab |= {w.casefold() for w in spelling.words(t)}
    out: list[Finding] = []
    by_page = {c["page"]: c for c in coverage}
    for p, pj in pairs:
        pb = B[pj]
        live = pb.get_text("words")
        if not live:
            by_page[p]["checks"].append(dict(name="Spelling", status="skipped", note="no text layer to read"))
            continue
        new, old = {}, set()
        for w in live:
            for tok in spelling.words(w[4]):
                if not spelling.checkable(tok) or spelling.is_known(tok, pw):
                    continue
                if tok.casefold() in vocab:
                    old.add(tok)
                else:
                    Hp = (page_H or {}).get(pj, (p, None))[1]
                    new.setdefault(tok, []).append(align.map_rect(Hp, list(w[:4])) if Hp is not None else list(w[:4]))
        for tok, rects in new.items():
            hint = spelling.suggest(tok)
            label = f'possible misspelling "{tok}"' + (f' (did you mean "{hint}"?)' if hint else "")
            hosts = [f for f in findings if f.page == p and f.bbox_b and any(_inter(f.bbox_b, r) > 0 for r in rects)
                     and f.category in ("text", "copydeck")]
            if hosts:
                for h in hosts:
                    h.detail.setdefault("spelling", []).append(label)
                    h.message += f"; {label}"
                continue
            out.append(Finding("spelling", "unknown_word", "minor", p,
                               f'Possible misspelling: "{tok}"' + (f' (did you mean "{hint}"?)' if hint else "") + " - not in the dictionary, the reference or the approved text",
                               b_text=tok, bbox_b=_union(rects), detail=dict(suggestion=hint, occurrences=len(rects))))
        note = f"{len(new)} new unknown word(s)" if new else "no new unknown words"
        if old:
            some = sorted(old, key=str.casefold)
            note += f"; {len(old)} unknown word(s) also in the reference, assumed intended: " + ", ".join(some[:12]) + (" ..." if len(some) > 12 else "")
        by_page[p]["checks"].append(dict(name="Spelling", status="ran", note=note))
    return out


# ── driver ────────────────────────────────────────────────────────────────
def _assign_confidence(f: Finding, raster: bool) -> None:
    """high: read straight from the PDF's own data or decoded. medium: inferred from rendered pixels,
    or a practical proxy rather than a standards-grade measurement. A reviewer should look at 'medium'
    findings first when time is short, and can trust 'high' ones to be exactly what the file says."""
    if f.confidence == "medium":
        return
    if f.kind in ("low_contrast", "low_reflectance", "quiet_zone_violation"):
        f.confidence = "medium"
    elif f.category == "layout" and f.detail.get("match", 1) < 0.95:
        f.confidence = "medium"
    elif raster and f.category in ("color", "layout", "graphic"):
        f.confidence = "medium"


def compare(path_a: str, path_b: str, cfg: Config | None = None, keep_images: bool = True, progress=None, deck: str | None = None,
            settings: dict | None = None, page_sink=None) -> Result:
    """page_sink(record) -> anything: called with each page's full-resolution images as soon as that page is done, and its
    return value is kept in Result.pages instead. That lets a caller turn a page into small screen images straight away, so
    memory doesn't grow with the page count. Without it, Result.pages holds the full-resolution images of every page."""
    cfg = cfg or Config()
    A, B = open_pdf(path_a), open_pdf(path_b)
    findings: list[Finding] = []
    warnings: list[str] = []
    pages, coverage, attention = [], [], []
    if len(A) != len(B):
        findings.append(Finding("structure", "page_count", "critical", 0, f"Page count differs: reference has {len(A)}, sample has {len(B)}"))
    pairs, lost, gained = _align_pages(A, B, cfg)
    moved_pages = [(p, pj) for p, pj in pairs if p != pj]
    if moved_pages:
        findings.append(Finding("structure", "page_order", "critical", moved_pages[0][0],
                                "Page order differs: " + ", ".join(f"reference page {p + 1} is sample page {pj + 1}" for p, pj in moved_pages)
                                + ". Pages were matched by content and compared in that pairing.",
                                detail=dict(mapping=[[p, pj] for p, pj in pairs])))
    for i in lost:
        findings.append(Finding("structure", "page_removed", "critical", i, f"Reference page {i + 1} has no matching page in the sample"))
    for j in gained:
        findings.append(Finding("structure", "page_added", "critical", min(j, max(len(A) - 1, 0)), f"Sample page {j + 1} has no matching page in the reference",
                                detail=dict(sample_page=j)))
    ocr_on = bool(cfg.ocr and ocr.available())
    page_H: dict = {}

    for done, (p, pj) in enumerate(pairs):
        if progress:
            progress(done, len(pairs))
        pa, pb = A[p], B[pj]
        if pa.rotation != pb.rotation:
            # a page whose /Rotate flag differs renders turned on its side, so everything would differ and every region
            # would go to OCR. Say so once, then compare with the flag undone (in memory only).
            findings.append(Finding("structure", "page_rotation", "major", p, f"Page rotation differs: {pa.rotation}° → {pb.rotation}°"))
            pb.set_rotation(pa.rotation)
        size_differs = abs(pa.rect.width - pb.rect.width) > cfg.size_tol_pt or abs(pa.rect.height - pb.rect.height) > cfg.size_tol_pt
        if size_differs:
            findings.append(Finding("structure", "page_size", "major", p,
                                    f"Page size differs: {pa.rect.width / MM:.1f} x {pa.rect.height / MM:.1f} mm → {pb.rect.width / MM:.1f} x {pb.rect.height / MM:.1f} mm"))
        img_a, img_b = _render(pa, cfg.dpi), _render(pb, cfg.dpi)
        has_a, has_b = bool(pa.get_text("words")), bool(pb.get_text("words"))
        no_text = not (has_a and has_b)
        # sub-pixel resampling differs when the page size differs, so use the looser image tolerance there too
        raster = no_text or size_differs
        if no_text:
            side = "sample" if has_a else ("reference" if has_b else "both files")
            if has_a or has_b:
                findings.append(Finding("info", "no_text_layer", "info", p,
                                        f"Page {p + 1}: {side} has no text layer (image-only / outlined artwork). Text cannot be compared word-by-word; "
                                        "compared visually with a looser tolerance instead. Request live-text artwork for a full text check."))
            else:
                warnings.append(f"Page {p + 1}: neither file has a text layer; visual comparison only.")

        codes = (_read_codes(img_a, cfg.dpi), _read_codes(img_b, cfg.dpi))
        # is the whole sample page shifted / scaled / rotated / photographed? report once, then compare aligned
        T = align.estimate(pa, pb, img_a, img_b, cfg.dpi, live=has_a and has_b, move_tol_mm=cfg.move_tol_mm) if cfg.register else None
        H = Hinv = None
        k_size = 1.0
        photo = False
        if T is not None:
            H, Hinv = T["H"], np.linalg.inv(T["H"])
            k_size = float(np.sqrt(abs(np.linalg.det(H[:2, :2]))))
            msg, sev = align.describe(T)
            findings.append(Finding("structure", "page_transform", sev, p, msg, confidence="high" if T["method"] == "text" else "medium",
                                    detail={k: v for k, v in T.items() if k != "H"}))
            img_b_own = img_b
            img_b = align.render_aligned(pb, H, img_a.shape, cfg.dpi) if T["kind"] == "similarity" else align.warp(img_b, H, img_a.shape, cfg.dpi)
            photo = not has_b and (T["kind"] == "perspective" or abs(T["rotation"]) > 0.3)
            if photo:
                img_b = align.flatfield(img_a, img_b)
                attention.append(dict(page=p, kind="photo_or_scan", side="sample", bbox=None,
                                      message=f"Page {p + 1}: the sample looks like a photo or a skewed scan. It was straightened and its lighting evened out "
                                              "before comparing, but fine detail can't be trusted like a PDF can - confirm anything important on the real artwork file."))
        text_f = [] if no_text else compare_text(pa, pb, p, cfg, k_size)
        lang_f = [] if no_text else compare_language(pa, pb, p)
        if lang_f:  # the whole page is a different language: a word-by-word diff would just be noise
            text_f = []
        code_f = compare_barcodes(img_a, img_b_own if T is not None else img_b, pa, pb, p, cfg, raster, codes=codes, H=H)
        color_f = compare_colorants(pa, pb, p, H)
        # a flattened/rasterised page has no vector drawings at all to read braille dots from, so
        # (like text) braille can't be meaningfully compared there - skip rather than claim "removed"
        brl_f = [] if raster else compare_braille(pa, pb, p)
        # a flattened page has no OCG/layer structure at all - "layer removed" would be uninformative
        # noise there, exactly like text and braille
        layer_f = [] if raster else compare_layers(A, B, pa, pb, p)
        struct_f = compare_structure(pa, pb, p, cfg, raster, H) + compare_inks(pa, pb, p)
        sep_f = [] if raster else compare_separations(pa, pb, p, cfg, H)
        if H is not None:  # everything read from the sample page itself is reported in the reference's frame
            for f in text_f + brl_f + layer_f:
                f.bbox_b = align.map_rect(H, f.bbox_b)
                if f.detail.get("block_b"):
                    f.detail["block_b"] = align.map_rect(H, f.detail["block_b"])
        # glyphs that changed obviously change the ink under them too; that is the text finding's job
        said = [r for f in text_f + code_f + brl_f + layer_f for r in (f.bbox_a, f.bbox_b, f.detail.get("block_a"), f.detail.get("block_b")) if r]
        sep_f = [sf for sf in sep_f if not any(_inter(_pad(r, 2), sf.bbox_a) > 0.3 * _area(sf.bbox_a) for r in said)]
        for sf in list(sep_f):
            host = next((c for c in color_f if c.bbox_a and _inter(_pad(c.bbox_a, 4), sf.bbox_a) > 0), None)
            if host is not None:  # same spot already reported from the vector colour: say what the inks did instead
                host.kind, host.message = "separation_changed", sf.message
                host.detail.update(sf.detail)
                host.severity = "major"
                sep_f.remove(sf)
        color_f += sep_f
        # the digits printed under a barcode are part of the barcode: fold their text changes into its finding
        zones = [(_pad(r, 16), f) for f in code_f if SEV_RANK[f.severity] >= 2 for r in (f.bbox_a, f.bbox_b) if r]
        for tf in list(text_f):
            rs = [r for r in (tf.bbox_a, tf.bbox_b) if r]
            host = next((f for z, f in zones if any(_inter(r, z) >= 0.5 * _area(r) for r in rs)), None)
            if host is not None:
                host.detail.setdefault("related_text", []).append(tf.message)
                if tf.bbox_a and host.bbox_a:
                    host.bbox_a = _union([host.bbox_a, tf.bbox_a])
                if tf.bbox_b and host.bbox_b:
                    host.bbox_b = _union([host.bbox_b, tf.bbox_b])
                text_f.remove(tf)
        explained = [[0, 0, pa.rect.width, pa.rect.height]] if lang_f else []  # whole page already explained: don't also flood it with per-glyph visual noise
        explained += [r for f in text_f + code_f + color_f + brl_f + layer_f + struct_f for r in (f.bbox_a, f.bbox_b) if r]
        explained += [r for f in text_f for r in (f.detail.get("block_a"), f.detail.get("block_b")) if r]
        explained += [_pad(f.bbox_a, 12) for f in code_f if f.bbox_a] + [_pad(f.bbox_b, 12) for f in code_f if f.bbox_b]
        # every decoded barcode's footprint is explained by the barcode check, whether or not it found
        # a problem - a barcode's own fine, high-frequency bar/module pattern is exactly what low-dpi
        # rasterisation aliases worst, and pixel agreement there is redundant anyway once the decoded
        # value, checksum, position and size have already been verified directly
        # on a pixel-aligned copy there is no aliasing to hide, so only the bars themselves are excluded and the
        # printed caption beside them stays under the pixel check
        vraster = raster or T is not None  # a registered sample has been resampled: tolerant path
        noise = _pair_noise(*_canvas(img_a, img_b)) if vraster else 0.0
        # live pages render identically on both sides (no aliasing), so they get the tight pad too
        qpad = -3.5 if (not vraster or (noise < 1.0 and img_a.shape == img_b.shape and T is None)) else 6  # compare_visual adds its own 4 pt margin, so -3.5 nets to ~0.5 pt around the bars
        if qpad > 0:  # only a resampled image-only copy needs the bars themselves kept out of the pixel check
            explained += [_pad(c["bbox"], qpad) for c in codes[0]]
            explained += [_pad(align.map_rect(H, c["bbox"]) if H is not None else c["bbox"], qpad) for c in codes[1]]
        if vraster and noise >= 1.0 and T is None:
            code_f += compare_captions(img_a, img_b, codes, p, cfg)
            explained += [r for f in code_f if f.kind == "caption_changed" for r in (f.bbox_a, f.bbox_b) if r]
        if vraster and noise >= 1.0 and has_a and not has_b and not photo:
            fp_f = compare_fine_print(pa, img_a, img_b, p, cfg, explained)
            code_f += fp_f
            explained += [f.bbox_a for f in fp_f]
        vcfg = dataclasses.replace(cfg, raster_blur=cfg.raster_blur * 2, raster_delta_e=cfg.raster_delta_e * 1.6,
                                   raster_delta_e_tight=cfg.raster_delta_e_tight * 3, min_area_px=cfg.min_area_px * 40) if photo else cfg
        vis_f, mask, vstats = compare_visual(img_a, img_b, pa, pb, p, explained, vcfg, vraster, noise, Hinv, k_size, registered=T is not None)
        if photo:
            for f in [f for f in code_f if f.kind in ("missing", "low_contrast", "low_reflectance", "quiet_zone_violation")]:
                code_f.remove(f)
                attention.append(dict(page=p, kind="photo_barcode", side="sample", bbox=f.bbox_a or f.bbox_b,
                                      message=f"Page {p + 1}: barcode {f.a_text or f.b_text} could not be verified from the photo - scan the physical pack or check the artwork file."))
        page_f = text_f + lang_f + code_f + color_f + brl_f + layer_f + struct_f + vis_f
        for f in page_f:
            _assign_confidence(f, raster)
        findings += page_f

        # what a person should look at even when nothing differs: printed barcode numbers with no
        # decodable symbol beside them (only where that side has a text layer to read them from)
        for side, page, cs, live in (("reference", pa, codes[0], has_a), ("sample", pb, codes[1], has_b)):
            if live:
                for digits, rect in _orphan_digit_strings(page, cs):
                    attention.append(dict(page=p, kind="unverified_barcode", side=side, bbox=list(rect),
                                          message=f'{side.capitalize()} page {p + 1}: "{digits}" is printed like a barcode number but no barcode could be decoded beside it, so no barcode check vouches for it'))

        if raster and vstats["noise"] >= 1.0:
            tiny = _tiny_text(pa if has_a else pb) if (has_a or has_b) else 0
            if tiny:
                attention.append(dict(page=p, kind="fine_print_resampled", side="both", bbox=None,
                                      message=f"Page {p + 1}: the image-only copy was resampled (noise {vstats['noise']:.0f}), and the live-text file has {tiny} text run(s) under 6 pt. "
                                              "A change to text that small can be missed by the pixel comparison; check fine print by eye or request live-text artwork."))
        n_brl = (len(_decode_braille(_braille_dots(pa))), len(_decode_braille(_braille_dots(pb)))) if not raster else None
        n_layers = (len(A.layer_ui_configs()), len(B.layer_ui_configs())) if not raster else None
        nshape = sum(1 for _ in _drawing_colors(pa))
        mode = "image-only" if (not has_a and not has_b) else ("mixed" if no_text else "live text")
        why = "no text layer" if no_text else "page sizes differ"
        checks = [
            dict(name="Text", status="skipped" if no_text else "ran", note=f"skipped: {why}" if no_text else "read from the PDF text layer, word by word"),
            dict(name="Barcodes", status="ran", note=f"{len(codes[0])} decoded in reference, {len(codes[1])} in sample"),
            dict(name="Vector colour", status="ran" if nshape else "skipped", note=f"{nshape} shapes read from the reference" if nshape else "no vector shapes on this page"),
            dict(name="Braille", status="skipped" if raster else "ran", note=f"skipped: {why}" if raster else f"{n_brl[0]} / {n_brl[1]} cell runs decoded (ref / sample)"),
            dict(name="Layers", status="skipped" if raster else "ran", note=f"skipped: {why}" if raster else f"{n_layers[0]} / {n_layers[1]} layers (ref / sample)"),
            dict(name="Ink separations", status="skipped" if raster else "ran",
                 note=f"skipped: {why}" if raster else f"C, M, Y and K plates compared at {cfg.separation_dpi} dpi"),
            dict(name="Page structure", status="ran", note="trim/bleed boxes, rotation, fonts, image resolution"),
            dict(name="Visual", status="ran", note=((f"{cfg.dpi} dpi CIE-Lab, pixel-aligned copy: full sensitivity" if vstats["aligned"] else f"{cfg.dpi} dpi CIE-Lab, resampled copy (noise {vstats['noise']:.0f}): tolerant, fine print may be missed") if raster else f"{cfg.dpi} dpi CIE-Lab") + f", {vstats['regions']} changed regions"),
            dict(name="OCR", status="ran" if ocr_on else "skipped",
                 note=(f"read {vstats['ocr_regions']} changed regions" if ocr_on else "engine not installed or disabled")),
        ]
        if T is not None:
            checks.insert(0, dict(name="Registration", status="ran", note=align.describe(T)[0].split(". ")[0] + f" ({T['inliers']} matching points)"))
        coverage.append(dict(page=p, sample_page=pj, mode=mode, limited=bool(raster or photo), checks=checks))
        if keep_images:
            rec = dict(page=p, sample_page=pj, img_a=img_a, img_b=img_b, mask=mask, dpi=cfg.dpi, aligned=T is not None,
                       H=H.tolist() if H is not None else None)
            pages.append(page_sink(rec) if page_sink else rec)
        page_H[pj] = (p, H)

    # ── document-level checks on the sample: approved text (copy deck) and spelling ──
    deck_paras: list[str] = []
    deck_note = dict(name="Approved text", status="skipped", note="no approved text document supplied")
    if deck:
        from . import copydeck
        if progress:
            progress(len(pairs), len(pairs) + 1)
        deck_paras = copydeck.load_deck(deck)
        deck_f, ds = copydeck.check(B, deck_paras, cfg.dpi)
        for f in deck_f:
            p_ref, Hp = page_H.get(f.page, (f.page, None))
            f.page = p_ref
            if Hp is not None:
                f.bbox_b = align.map_rect(Hp, f.bbox_b)
        # An OCR reading that disagrees with the approved text is only a finding if the pixel comparison also saw
        # a change there. Otherwise the artwork matches the approved reference at that spot, and the likeliest
        # explanation is an OCR misread - so it is raised for a person to check instead of claimed as a defect.
        others = [f for f in findings if f.category not in ("info", "copydeck")]
        unconfirmed: dict = {}
        for f in deck_f:
            if f.confidence != "medium":
                findings.append(f)
                continue
            box = f.bbox_b
            seen = box and any(o.page == f.page and any(r and _inter(r, _pad(box, 6)) > 0 for r in (o.bbox_a, o.bbox_b)) for o in others)
            if seen:
                findings.append(f)
            else:
                unconfirmed.setdefault(f.page, []).append(f)
        # one note per page, not one per OCR hiccup
        for pg, fs in sorted(unconfirmed.items()):
            ex = "; ".join(x.message.split(": ", 1)[-1][:70] for x in fs[:3])
            attention.append(dict(page=pg, kind="ocr_unconfirmed", side="sample", bbox=next((x.bbox_b for x in fs if x.bbox_b), None),
                                  message=f"Page {pg + 1}: {len(fs)} place(s) where OCR of the image-only sample doesn't match the approved text, but the "
                                          f"artwork matches the reference there - most likely OCR misreads (small, rotated or stylised text). Check by eye: {ex}"
                                          + (" ..." if len(fs) > 3 else "")))
        deck_note = dict(name="Approved text", status="ran",
                         note=f"{ds['matched']} of {ds['paragraphs']} approved paragraphs located on the sample" + (" (read by OCR)" if ds["ocr"] else ""))
    findings += _spelling(A, B, pairs, findings, deck_paras, coverage, page_H)
    findings = _merge_confirmations(findings)
    if settings:
        from . import profiles
        findings = profiles.apply(findings, settings)
    for c in coverage:
        c["checks"].append(deck_note)

    findings.sort(key=lambda f: (f.page, -SEV_RANK[f.severity], (f.bbox_a or f.bbox_b or [0, 0])[1], (f.bbox_a or f.bbox_b or [0, 0])[0]))
    for i, f in enumerate(findings, 1):
        f.id = i
    return Result(findings, pages, warnings, coverage, attention)
