"""Copy-deck check: does the artwork say exactly what the approved text document says?

Pharma artwork is approved against a text document (the "copy deck", usually Word), not only against the
previous PDF. Each approved paragraph is located on the artwork wherever it sits (panel order, columns and
line breaks differ from the document), then diffed word by word. Reported:

  - text_changed   the paragraph is on the artwork, but some words differ
  - missing        an approved paragraph can't be found on the artwork at all
  - not_in_deck    text on the artwork that no approved paragraph accounts for

Live-text artwork is read from the PDF's text layer. Image-only artwork is read with OCR, and those findings
are marked medium confidence.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
import zipfile
from pathlib import Path

import numpy as np
import pymupdf

from . import ocr
from .compare import Finding, _render, _text_blocks, _text_severity, _union

_PUNCT = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " ", "­": "-"})


def norm(t: str) -> str:
    return unicodedata.normalize("NFKC", t).translate(_PUNCT)


# ── reading the approved text ─────────────────────────────────────────────
def load_deck(path: str) -> list[str]:
    """Paragraphs of the approved text. .docx (body and tables, in order), .txt (one paragraph per line) or
    .pdf (one paragraph per text block)."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".docx":
        paras = _docx_paragraphs(p)
    elif ext in (".txt", ".md"):
        paras = p.read_text(encoding="utf-8", errors="replace").splitlines()
    elif ext == ".pdf":
        doc = pymupdf.open(p)
        paras = [b["text"] for pg in doc for b in _text_blocks(pg)]
    else:
        raise ValueError(f"Unsupported approved-text format: {ext} (use .docx, .txt or .pdf)")
    return [re.sub(r"\s+", " ", norm(x)).strip() for x in paras if x and x.strip()]


def _docx_paragraphs(path: Path) -> list[str]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = docx.Document(str(path))
    out = []
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            out.append(Paragraph(el, d).text)
        elif tag == "tbl":
            for row in Table(el, d).rows:
                seen = set()
                for cell in row.cells:
                    if id(cell._tc) in seen:  # merged cells repeat
                        continue
                    seen.add(id(cell._tc))
                    out += [pp.text for pp in cell.paragraphs]
    return out


def write_docx(paragraphs: list[str], path: str, title: str = "") -> None:
    import docx
    d = docx.Document()
    if title:
        d.add_heading(title, level=1)
    for t in paragraphs:
        d.add_paragraph(t)
    d.save(path)


# ── reading the artwork ───────────────────────────────────────────────────
def _live_blocks(page, pno: int) -> list[dict]:
    out = []
    for b in _text_blocks(page):
        words = []
        for w in b["words"]:
            t = norm(w[4])
            # re-join words hyphenated across a line break: "suspen-" / "sion"
            if words and words[-1]["t"].endswith("-") and len(words[-1]["t"]) > 2 and t[:1].islower() and w[1] > words[-1]["r"][3] - 1:
                prev = words[-1]
                prev["t"] = prev["t"][:-1] + t
                prev["r"] = _union([prev["r"], list(w[:4])])
                continue
            words.append(dict(t=t, r=list(w[:4])))
        out.append(dict(page=pno, words=words, ocr=False))
    return out


def _ocr_blocks(page, pno: int, dpi: int) -> list[dict]:
    """Image-only page: OCR lines (upright and vertical), split into words with boxes proportional to character
    position along the line's reading direction."""
    if ocr._get() is None:
        return []
    img = _render(page, dpi)
    k = 72 / dpi
    lines = []
    for box, txt, conf, ang in ocr.page_lines(img):
        xs, ys = box[:, 0] * k, box[:, 1] * k
        x0, x1, y0, y1 = float(xs.min()), float(xs.max()), float(ys.min()), float(ys.max())
        txt = norm(txt)
        words, n = [], max(1, len(txt))
        for m in re.finditer(r"\S+", txt):
            a_, b_ = m.start() / n, m.end() / n
            if ang == 0:
                r = [x0 + a_ * (x1 - x0), y0, x0 + b_ * (x1 - x0), y1]
            elif ang == 90:  # reads bottom-to-top
                r = [x0, y1 - b_ * (y1 - y0), x1, y1 - a_ * (y1 - y0)]
            else:            # reads top-to-bottom
                r = [x0, y0 + a_ * (y1 - y0), x1, y0 + b_ * (y1 - y0)]
            words.append(dict(t=m.group(), r=r))
        lines.append(dict(page=pno, words=words, ocr=True, y=y0, x=x0, h=(y1 - y0) if ang == 0 else (x1 - x0), ang=ang))
    # stack upright lines into paragraph-ish blocks: same left edge region, small vertical gap; vertical lines stand alone
    lines.sort(key=lambda l: (l["y"], l["x"]))
    blocks: list[dict] = []
    for ln in lines:
        if ln["ang"] == 0:
            for b in blocks:
                last = b.get("_last")
                if last and abs(ln["x"] - last["x"]) < 3 * ln["h"] and 0 <= ln["y"] - (last["y"] + last["h"]) < 0.8 * ln["h"]:
                    b["words"] += ln["words"]; b["_last"] = ln
                    break
            else:
                blocks.append(dict(page=pno, words=list(ln["words"]), ocr=True, _last=ln))
        else:
            blocks.append(dict(page=pno, words=list(ln["words"]), ocr=True, _last=None))
    for b in blocks:
        b.pop("_last", None)
    return blocks


def artwork_blocks(doc, dpi: int = 300) -> list[dict]:
    out = []
    for pno, page in enumerate(doc):
        out += _live_blocks(page, pno) if page.get_text("words") else _ocr_blocks(page, pno, dpi)
    return out


# ── matching ──────────────────────────────────────────────────────────────
# Live text is compared word by word. OCR'd text is compared character by character with whitespace removed,
# because OCR routinely drops or adds spaces ("Donot") and that must not look like a wording change.
_CJK = "\u3000-\u303f\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uff00-\uffef"
_TOK = re.compile(f"[{_CJK}]|[^\\s{_CJK}]+")


def _units(text: str, ocr_mode: bool) -> list[str]:
    # scripts written without spaces (Chinese, Japanese) are compared character by character
    return list(re.sub(r"\s+", "", text)) if ocr_mode else _TOK.findall(text)


def _block_units(b: dict) -> tuple[list[str], list[list]]:
    if not b["ocr"]:
        us, rs = [], []
        for w in b["words"]:
            for t in _TOK.findall(w["t"]):
                us.append(t)
                rs.append(w["r"])
        return us, rs
    us, rs = [], []
    for w in b["words"]:
        for ch in w["t"]:
            us.append(ch)
            rs.append(w["r"])
    return us, rs


def _key(t: str) -> str:
    if len(t) == 1:
        if t in "Iil|":
            return "l"
        if t in "ßB":
            return "b"  # OCR reads the German sharp s as a capital B  # OCR can't reliably tell I / i / l apart; letter-for-letter only, never digits
        return unicodedata.normalize("NFKD", t)[0].casefold()  # nor accents: a / à / á
    return t.casefold().strip(".,;:!?()[]\"'") or t


def _window(D: list[str], A: list[str]) -> tuple[float, int, int]:
    """Best contiguous window of A that aligns with D. Returns (score, j0, j1); score = 2M / (|D| + |window|),
    plus a small bonus for an exact-case match so "Adults" prefers "Adults" over "adults"."""
    if not D or not A:
        return 0.0, 0, 0
    kd, ka = [_key(t) for t in D], [_key(t) for t in A]
    mb = [b for b in difflib.SequenceMatcher(None, kd, ka, autojunk=False).get_matching_blocks() if b.size]
    if not mb:
        return 0.0, 0, 0
    anchor = max(mb, key=lambda b: b.size)
    reach = 1.5 * len(D) + 2
    keep = [b for b in mb if b.b >= anchor.b - reach and b.b + b.size <= anchor.b + anchor.size + reach]
    j0 = max(0, keep[0].b - keep[0].a)
    j1 = min(len(A), keep[-1].b + keep[-1].size + (len(D) - keep[-1].a - keep[-1].size))
    m = sum(b.size for b in difflib.SequenceMatcher(None, kd, ka[j0:j1], autojunk=False).get_matching_blocks())
    exact = sum(b.size for b in difflib.SequenceMatcher(None, D, A[j0:j1], autojunk=False).get_matching_blocks())
    n = len(D) + (j1 - j0)
    return 2 * m / n + 0.02 * (2 * exact / n), j0, j1


def _tiles(run: list[str], paras: list[list[str]]) -> bool:
    """Can `run` be written as back-to-back exact copies of approved paragraphs? (OCR reads a table row
    "20 mg | 10 mg | 10 mg" as one line; each cell is approved on its own.)"""
    ks = [[_key(t) for t in p] for p in paras if p]
    kr = [_key(t) for t in run]
    reach = [False] * (len(kr) + 1)
    reach[0] = True
    for i in range(len(kr)):
        if reach[i]:
            for p in ks:
                if kr[i:i + len(p)] == p:
                    reach[i + len(p)] = True
    return reach[-1]


def _severity(ea, eb, ta, tb, ocr_mode):
    sev = _text_severity([x for x in ea if x], [x for x in eb if x])
    if ocr_mode and sev != "critical" and re.search(r"\d(mg|mcg|µg|μg|ml|g|kg|iu|%)", (ta + " " + tb).casefold()):
        sev = "critical"  # character-level OCR edits split units ("mg" -> "mcg" is an inserted "c"); judge by context
    return sev


def _contains(seq: list[str], sub: list[str]) -> bool:
    n = len(sub)
    return n > 0 and any(seq[i:i + n] == sub for i in range(len(seq) - n + 1))


def _diff(D, A, R, ocr_mode):
    """Edits between approved units D and artwork units A (rects R). In character mode, edits within 2
    characters of each other merge into one readable change, shown with a little context."""
    edits = []
    # OCR can't be trusted on letter case or on I vs l, so in character mode compare folded keys
    cd, ca = ([_key(t) for t in D], [_key(t) for t in A]) if ocr_mode else (D, A)
    for tag, i1, i2, k1, k2 in difflib.SequenceMatcher(None, cd, ca, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if ocr_mode and edits and i1 - edits[-1][1] <= 2 and k1 - edits[-1][3] <= 2:
            e = edits[-1]
            edits[-1] = (e[0], i2, e[2], k2)
        else:
            edits.append((i1, i2, k1, k2))
    out = []
    for i1, i2, k1, k2 in edits:
        if ocr_mode:
            c1, c2, d1, d2 = max(0, i1 - 3), min(len(D), i2 + 3), max(0, k1 - 3), min(len(A), k2 + 3)
            # put the spaces back for display: a new OCR word starts wherever the character's word box changes
            ta = "".join(D[c1:c2])
            tb = "".join((" " if x > d1 and R[x] is not R[x - 1] else "") + A[x] for x in range(d1, d2))
            ea, eb = ["".join(D[i1:i2])], ["".join(A[k1:k2])]
        else:
            ta, tb, ea, eb = " ".join(D[i1:i2]), " ".join(A[k1:k2]), D[i1:i2], A[k1:k2]
        # include the neighbouring units so a deletion is boxed where the text used to be
        rect = _union(R[max(0, k1 - 1):min(len(R), k2 + 1)]) if ocr_mode else (_union(R[k1:k2]) or _union(R[max(0, k1 - 1):k1 + 1]))
        out.append((ta, tb, ea, eb, i2 > i1, k2 > k1, rect, i1, i2))
    return out


def _free_runs(cov) -> list[tuple[int, int]]:
    runs, j, n = [], 0, len(cov)
    while j < n:
        if cov[j]:
            j += 1
            continue
        k = j
        while k < n and not cov[k]:
            k += 1
        runs.append((j, k))
        j = k
    return runs


def check(doc, deck_paras: list[str], dpi: int = 300, min_score: float = 0.5) -> tuple[list[Finding], dict]:
    from .compare import _inter, _pad, _read_codes
    blocks = artwork_blocks(doc, dpi)
    used_ocr = any(b["ocr"] for b in blocks)
    # barcode captions are verified against the bars by the barcode check; keep them out of the text check
    codes = {pno: [c["bbox"] for c in _read_codes(_render(pg, dpi), dpi)] for pno, pg in enumerate(doc)}
    units = [_block_units(b) for b in blocks]
    covered = [np.zeros(len(u[0]), bool) for u in units]
    dunits = {m: [_units(t, m) for t in deck_paras] for m in (False, True)}
    out: list[Finding] = []

    def locate(D_of):
        """Best place for an approved unit sequence, searching only artwork text no other paragraph has claimed."""
        best = (0.0, -1, 0, 0)
        for bi, b in enumerate(blocks):
            D = D_of(b["ocr"])
            for r0, r1 in _free_runs(covered[bi]):
                s, j0, j1 = _window(D, units[bi][0][r0:r1])
                if s > best[0]:
                    best = (s, bi, r0 + j0, r0 + j1)
        return best

    pending = []

    def emit(D, bi, j0, j1, di, depth=0):
        b = blocks[bi]
        covered[bi][j0:j1] = True
        A, R = units[bi][0][j0:j1], units[bi][1][j0:j1]
        for ta, tb, ea, eb, has_a, has_b, rect, i1, i2 in _diff(D, A, R, b["ocr"]):
            if has_a and not has_b and depth < 3 and (i2 - i1) >= (5 if b["ocr"] else 3):
                # the "missing" words may simply sit in another block (a paragraph split by an edit or by layout);
                # decided only after every paragraph has claimed its own text, so this can't steal a neighbour's words
                pending.append((D[i1:i2], b["ocr"], di, depth + 1, (ta, tb, ea, eb, has_a, has_b, rect), b))
                continue
            report(ta, tb, ea, eb, has_a, has_b, rect, b, di)

    def respace(t: str, di: int) -> str:
        """The approved paragraph's own spacing for a whitespace-free OCR comparison snippet."""
        if not t:
            return t
        m = re.search(r"\s*".join(re.escape(ch) for ch in t), deck_paras[di])
        return m.group(0) if m else t

    def report(ta, tb, ea, eb, has_a, has_b, rect, b, di):
        if b["ocr"]:
            ta = respace(ta, di)
        if has_a and not has_b:
            msg = f'Approved text "{ta}" is missing on the artwork'
        elif has_b and not has_a:
            msg = f'Artwork adds "{tb}", which is not in the approved text'
        else:
            msg = f'Approved text says "{ta}" but the artwork reads "{tb}"'
        out.append(Finding("copydeck", "text_changed", _severity(ea, eb, ta, tb, b["ocr"]), b["page"], msg,
                           a_text=ta, b_text=tb, bbox_b=rect and list(rect),
                           detail=dict(deck_index=di, context=deck_paras[di][:160]), confidence="medium" if b["ocr"] else "high"))

    def place_part(seg, ocr_mode, di, depth) -> bool:
        """Place the matching core of a deleted segment elsewhere; report only what truly is not there."""
        s, bi, j0, j1 = locate(lambda o: seg if o == ocr_mode else [])
        if bi < 0 or blocks[bi]["ocr"] != ocr_mode:
            return False
        kd, ka = [_key(t) for t in seg], [_key(t) for t in units[bi][0][j0:j1]]
        mb = [m for m in difflib.SequenceMatcher(None, kd, ka, autojunk=False).get_matching_blocks() if m.size]
        if not mb:
            return False
        lo, hi = mb[0].a, mb[-1].a + mb[-1].size
        core = seg[lo:hi]
        s2, bi2, k0, k1 = locate(lambda o: core if o == ocr_mode else [])
        if bi2 < 0 or s2 < 0.8 or len(core) < (5 if ocr_mode else 3):
            return False
        emit(core, bi2, k0, k1, di, depth)
        for rest, edge in ((seg[:lo], k0), (seg[hi:], k1 - 1)):
            if ocr_mode and (not any(ch.isalnum() for ch in rest) or (len("".join(rest).strip(".,;: ")) == 1 and "".join(rest).strip(".,;: ").isalpha())):
                continue  # a stray full stop at a paragraph split is OCR segmentation, not a wording change
            if rest and not place_part(rest, ocr_mode, di, depth + 1):
                b = blocks[bi2]
                ta = ("" if ocr_mode else " ").join(rest)
                out.append(Finding("copydeck", "text_changed", _severity(rest, [], ta, "", ocr_mode), b["page"],
                                   f'Approved text "{ta}" is missing on the artwork', a_text=ta,
                                   bbox_b=list(units[bi2][1][edge]), detail=dict(deck_index=di, context=deck_paras[di][:160]),
                                   confidence="medium" if ocr_mode else "high"))
        return True

    # 1. place every approved paragraph, longest first so short ones can't claim a spot inside a long one
    matched = 0
    for di in sorted(range(len(deck_paras)), key=lambda i: -len(deck_paras[i])):
        s, bi, j0, j1 = locate(lambda o: dunits[o][di])
        if s < min_score:
            has_d = bool(re.search(r"\d", deck_paras[di]))
            out.append(Finding("copydeck", "missing", "critical" if has_d else "major", 0,
                               f'Approved text not found on the artwork: "{deck_paras[di]}"', a_text=deck_paras[di],
                               detail=dict(deck_index=di, best_score=round(min(s, 1.0), 2)), confidence="medium" if used_ocr else "high"))
            continue
        matched += 1
        emit(dunits[blocks[bi]["ocr"]][di], bi, j0, j1, di)
    while pending:
        seg, om, di, depth, rep_args, b = pending.pop(0)
        if not place_part(seg, om, di, depth):
            report(*rep_args, b, di)

    # 2. whatever is left on the artwork: a repeat of approved text (brand on every panel, blister cells), a
    #    near-repeat with an error in it, or text the approved document doesn't contain at all
    for bi, b in enumerate(blocks):
        us, rs = units[bi]
        j = 0
        while j < len(us):
            if covered[bi][j]:
                j += 1
                continue
            k = j
            while k < len(us) and not covered[bi][k]:
                k += 1
            run, rr = us[j:k], rs[j:k]
            text = ("" if b["ocr"] else " ").join(run)
            j = k
            digits_only = bool(re.fullmatch(r"[\d\s]+", text))
            if any(_inter(r, _pad(z, 16 if digits_only else 4)) > 0.5 * max(1e-6, (r[2] - r[0]) * (r[3] - r[1])) for r in rr for z in codes.get(b["page"], [])):
                continue
            if re.fullmatch(r"[\d\s]{8,}", text) or not re.search(r"\w", text):
                continue
            # an exact repeat of approved wording. A short fragment only counts if it is a whole approved paragraph -
            # otherwise a word deleted from one of many repeated cells would pass as "a repeat of the rest"
            long_run = len(run) >= (12 if b["ocr"] else 3)
            if any(dunits[b["ocr"]][di] == run or (long_run and _contains(dunits[b["ocr"]][di], run)) for di in range(len(deck_paras))):
                continue
            if b["ocr"] and _tiles(run, dunits[True]):
                continue  # an OCR line that joined several approved table cells
            s, di, w0, w1 = 0.0, -1, 0, 0
            for d in range(len(deck_paras)):
                sc, a0, a1 = _window(run, dunits[b["ocr"]][d])
                if sc > s:
                    s, di, w0, w1 = sc, d, a0, a1
            if s >= 0.6:  # a repeated panel whose wording differs from the approved text
                emit(dunits[b["ocr"]][di][w0:w1], bi, j - len(run), j, di, depth=3)
                continue
            out.append(Finding("copydeck", "not_in_deck", _severity([], [text] if b["ocr"] else run, "", text, b["ocr"]), b["page"],
                               f'Artwork text not in the approved text: "{text}"', b_text=text,
                               bbox_b=list(_union(rr)), confidence="medium" if b["ocr"] else "high"))
    return out, dict(paragraphs=len(deck_paras), matched=matched, ocr=used_ocr)
