"""Hard blind test: multiple defects per pair, known weak spots, and cases the tool is not built for yet.

    python make_hard.py      # -> blind_test_hard/pair_XX_*.pdf (+ approved text) and ANSWER_KEY.txt

Run every pair first. The answer key says what was changed AND which bucket each pair is in:
    [SHOULD CATCH]     within what the tool claims to handle
    [MAY STRUGGLE]     supported, but near a known limit
    [NOT SUPPORTED]    outside what the tool is built for today; how it fails is the interesting part
"""
from __future__ import annotations

import random
import re
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

import newdesigns
from mutate import MUTATORS, _erase, _rgb, _word_style, flatten
from proofer.compare import _text_blocks
from proofer.copydeck import write_docx

ROOT = Path(__file__).parent
OUT = ROOT / "blind_test_hard"
MM = 72 / 25.4


def build(name: str, path: Path) -> Path:
    newdesigns.build(name, str(path))
    return path


def deck_for(pdf: Path, dst: Path) -> None:
    paras, seen = [], set()
    for pg in pymupdf.open(pdf):
        for b in _text_blocks(pg):
            if b["text"] not in seen and not re.fullmatch(r"[\d\s]{8,}", b["text"]):
                seen.add(b["text"]); paras.append(b["text"])
    random.Random(str(pdf)).shuffle(paras)
    write_docx(paras, str(dst))


def replace_word(pg, old: str, new: str, font: str | None = None) -> bool:
    for w in pg.get_text("words"):
        if w[4] == old:
            sp = _word_style(pg, w)
            _erase(pg, [w[0] + 0.3, w[1] + 0.3, w[2] - 0.3, w[3] - 0.3])
            f = font or ("cobo" if "Courier" in sp["font"] and "Bold" in sp["font"] else "cour" if "Courier" in sp["font"]
                         else "tibo" if "Times" in sp["font"] and "Bold" in sp["font"] else "tiro" if "Times" in sp["font"]
                         else "hebo" if "Bold" in sp["font"] else "helv")
            pg.insert_text((w[0], sp["origin"][1]), new, fontsize=sp["size"], fontname=f, color=_rgb(sp["color"]))
            return True
    return False


def transform_page(src: Path, dst: Path, dx=0.0, dy=0.0, scale=1.0) -> None:
    """Re-impose every page: shifted and/or scaled, text stays live (as a real re-export would leave it)."""
    s = pymupdf.open(src)
    out = pymupdf.open()
    for i, p in enumerate(s):
        W, H = p.rect.width, p.rect.height
        np_ = out.new_page(width=W, height=H)
        w2, h2 = W * scale, H * scale
        x0, y0 = (W - w2) / 2 + dx, (H - h2) / 2 + dy
        np_.show_pdf_page(pymupdf.Rect(x0, y0, x0 + w2, y0 + h2), s, i)
    out.save(dst)


def phone_photo(src: Path, dst: Path, seed=0) -> None:
    """Simulate a phone snapshot of the printed pack: slight rotation, perspective, blur, uneven light, noise."""
    rng = np.random.default_rng(seed)
    s = pymupdf.open(src)
    out = pymupdf.open()
    for p in s:
        pix = p.get_pixmap(dpi=200, alpha=False)
        im = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3).astype(np.float32)
        h, w = im.shape[:2]
        src_pts = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        j = lambda: rng.uniform(-0.012, 0.012) * w
        dst_pts = np.float32([[j(), j()], [w + j(), j()], [w + j(), h + j()], [j(), h + j()]])
        M = cv2.getPerspectiveTransform(src_pts, dst_pts)
        im = cv2.warpPerspective(im, M, (w, h), borderValue=(235, 232, 228))
        R = cv2.getRotationMatrix2D((w / 2, h / 2), 1.3, 1.0)
        im = cv2.warpAffine(im, R, (w, h), borderValue=(235, 232, 228))
        im = cv2.GaussianBlur(im, (0, 0), 1.1)
        yy, xx = np.mgrid[0:h, 0:w]
        im *= (0.85 + 0.2 * (xx / w))[..., None] * (0.95 + 0.05 * (yy / h))[..., None]
        im += rng.normal(0, 4, im.shape)
        im = np.clip(im, 0, 255).astype(np.uint8)
        np_ = out.new_page(width=p.rect.width, height=p.rect.height)
        np_.insert_image(np_.rect, pixmap=pymupdf.Pixmap(pymupdf.csRGB, w, h, im.tobytes(), False))
    out.save(dst)


def cjk_label(path: Path, strength: str, warn: str) -> None:
    doc = pymupdf.open()
    pg = doc.new_page(width=110 * MM, height=60 * MM)
    pg.draw_rect(pymupdf.Rect(0, 0, pg.rect.width, 40), color=None, fill=(0.75, 0.1, 0.15))
    pg.insert_text((12, 28), "康宁颗粒", fontsize=18, fontname="china-s", color=(1, 1, 1))
    pg.insert_text((12, 62), f"每袋含对乙酰氨基酚 {strength}", fontsize=9, fontname="china-s")
    pg.insert_text((12, 80), "用法用量：成人一次一袋，一日三次。", fontsize=8, fontname="china-s")
    pg.insert_text((12, 98), warn, fontsize=8, fontname="china-s")
    pg.insert_text((12, 116), "贮藏：密封，置阴凉干燥处。", fontsize=8, fontname="china-s")
    pg.insert_text((12, 160), "Fictional sample", fontsize=4, fontname="helv", color=(0.5, 0.5, 0.5))
    doc.save(path)


def rich_black_label(path: Path, cmyk) -> None:
    """A black panel specified in CMYK. K-only and 'rich black' look the same on screen but print differently."""
    doc = pymupdf.open()
    pg = doc.new_page(width=80 * MM, height=50 * MM)
    pg.draw_rect(pymupdf.Rect(10, 10, pg.rect.width - 10, 70), color=None, fill=cmyk)
    pg.insert_text((20, 45), "NOCTURA", fontsize=20, fontname="hebo", color=(1, 1, 1))
    pg.insert_text((14, 95), "Melatonin 1 mg - 30 tablets", fontsize=9, fontname="helv")
    pg.insert_text((14, 112), "Take 1 tablet 1 hour before sleep.", fontsize=7, fontname="helv")
    pg.insert_text((14, 135), "Fictional sample", fontsize=4, fontname="helv", color=(0.5, 0.5, 0.5))
    doc.save(path)


def spot_label(path: Path, spot: str, overprint: bool) -> None:
    """A label whose brand band is printed in a named spot colour (e.g. a Pantone), optionally set to overprint."""
    d = pymupdf.open()
    p = d.new_page(width=80 * MM, height=50 * MM)
    fn = d.get_new_xref()
    d.update_object(fn, "<< /FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] /C1 [1 0.6 0 0.2] /N 1 >>")
    cs = d.get_new_xref()
    d.update_object(cs, f"[ /Separation /{spot.replace(' ', '#20')} /DeviceCMYK {fn} 0 R ]")
    gs = d.get_new_xref()
    d.update_object(gs, f"<< /Type /ExtGState /OP {'true' if overprint else 'false'} /op {'true' if overprint else 'false'} /OPM 1 >>")
    font = d.get_new_xref()
    d.update_object(font, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    res = d.get_new_xref()
    d.update_object(res, f"<< /ColorSpace << /CS0 {cs} 0 R >> /ExtGState << /GS0 {gs} 0 R >> /Font << /F1 {font} 0 R >> >>")
    c = d.get_new_xref()
    d.update_object(c, "<< >>")
    d.update_stream(c, b"q /GS0 gs /CS0 cs 1 scn 10 60 207 70 re f Q BT /F1 18 Tf 1 1 1 rg 22 85 Td (AQUAVITA) Tj ET "
                       b"BT /F1 8 Tf 0 0 0 rg 20 40 Td (Oral rehydration salts - 10 sachets) Tj ET")
    d.xref_set_key(p.xref, "Resources", f"{res} 0 R")
    d.xref_set_key(p.xref, "Contents", f"{c} 0 R")
    d.save(path)


def main(seed: int | None = None) -> int:
    rng = random.Random(seed)
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    tmp = OUT / "_work"
    tmp.mkdir()
    cases = []

    def case(bucket, what, ref, smp, deck_src=None):
        cases.append((bucket, what, ref, smp, deck_src))

    # ── [SHOULD CATCH] several defects at once ──
    for name, n, flat in (("vitamins", 4, False), ("nasal", 3, False), ("cream", 3, True), ("eyedrops", 5, False)):
        ref = build(name, tmp / f"{name}_ref_{len(cases)}.pdf")
        doc = pymupdf.open(ref)
        done = []
        for _ in range(n):
            for _try in range(30):
                mut = rng.choice(list(MUTATORS))
                pno = rng.randrange(len(doc))
                res = MUTATORS[mut](doc[pno], random.Random(rng.random()))
                if res:
                    done.append(f"page {pno + 1}: {res[0]}")
                    break
        smp = tmp / f"{name}_smp_{len(cases)}.pdf"
        doc.save(smp, garbage=1)
        if flat:
            f2 = tmp / f"{name}_flat_{len(cases)}.pdf"
            flatten(str(smp), str(f2)); smp = f2
            done.append("(sample flattened to image-only at 300 dpi)")
        case("SHOULD CATCH", f"{len([d for d in done if not d.startswith('(')])} defects: " + "; ".join(done), ref, smp, ref)

    # ── [MAY STRUGGLE] ──
    ref = build("eyedrops", tmp / "eye_lookalike_ref.pdf")
    doc = pymupdf.open(ref)
    replace_word(doc[0], "OC-5518", "0C-5518")  # letter O -> digit zero, rotated lot line
    smp = tmp / "eye_lookalike_smp.pdf"; doc.save(smp)
    f2 = tmp / "eye_lookalike_flat.pdf"; flatten(str(smp), str(f2))
    case("MAY STRUGGLE", 'Lot "OC-5518" -> "0C-5518" (letter O became digit zero) in rotated side text; sample flattened to image-only', ref, f2, ref)

    ref = build("nasal", tmp / "nasal_rnm_ref.pdf")
    doc = pymupdf.open(ref)
    replace_word(doc[1], "remove", "rernove") or replace_word(doc[1], "Remove", "Rernove")
    smp = tmp / "nasal_rnm_smp.pdf"; doc.save(smp)
    f2 = tmp / "nasal_rnm_flat.pdf"; flatten(str(smp), str(f2))
    case("MAY STRUGGLE", 'Page 2: "Remove" -> "Rernove" ("m" replaced by lookalike "rn"); sample flattened to image-only', ref, f2, ref)

    ref = build("insulin", tmp / "ins_fine_ref.pdf")
    doc = pymupdf.open(ref)
    replace_word(doc[0], "28", "26")
    smp = tmp / "ins_fine_smp.pdf"; doc.save(smp)
    f2 = tmp / "ins_fine_flat150.pdf"; flatten(str(smp), str(f2), dpi=150)
    case("MAY STRUGGLE", '"up to 28 days" -> "up to 26 days" in 4 pt fine print; sample flattened at only 150 dpi', ref, f2, ref)

    ref = build("cream", tmp / "cream_shift_ref.pdf")
    doc = pymupdf.open(ref)
    replace_word(doc[1], "06/2028", "06/2029")
    smp0 = tmp / "cream_shift_smp0.pdf"; doc.save(smp0)
    smp = tmp / "cream_shift_smp.pdf"; transform_page(smp0, smp, dx=1.0 * MM, dy=0.6 * MM)
    case("MAY STRUGGLE", 'Page 2: expiry "06/2028" -> "06/2029", hidden inside a file where BOTH pages were re-imposed 1.0 mm right and 0.6 mm down', ref, smp, ref)

    ref = build("nasal", tmp / "nasal_swap_ref.pdf")
    doc = pymupdf.open(ref)
    doc.move_page(1, 0)
    smp = tmp / "nasal_swap_smp.pdf"; doc.save(smp)
    case("MAY STRUGGLE", "The two pages are in swapped order (content otherwise identical)", ref, smp, ref)

    ref = build("vitamins", tmp / "vit_de_ref.pdf")
    orig = newdesigns._rgb
    newdesigns._rgb = lambda h: tuple(min(1, c + 0.012) for c in orig(h)) if h == "#e8731a" else orig(h)
    smp = build("vitamins", tmp / "vit_de_smp.pdf")
    newdesigns._rgb = orig
    case("MAY STRUGGLE", "Orange brand panel drifted by about 3/255 per channel (roughly ΔE 1.5) - below the default visual threshold; a brand-colour tolerance question", ref, smp, ref)

    ref = build("vitamins", tmp / "vit_bold_ref.pdf")
    doc = pymupdf.open(ref)
    replace_word(doc[0], "Supplement", "Supplement", font="helv")
    smp = tmp / "vit_bold_smp.pdf"; doc.save(smp)
    case("SHOULD CATCH", '"Supplement" in the table heading changed from bold to regular weight (wording identical)', ref, smp, ref)

    # ── [NOT SUPPORTED] ──
    ref = build("eyedrops", tmp / "eye_photo_ref.pdf")
    smp = tmp / "eye_photo_smp.pdf"; phone_photo(ref, smp, seed=5)
    case("NOT SUPPORTED", "NO artwork change. The sample is a simulated phone photo of the pack (tilted 1.3°, perspective, blur, uneven light). "
                          "Ideal answer: 'can't compare a photo reliably'; expect lots of false findings instead", ref, smp, ref)

    ref = build("cream", tmp / "cream_scale_ref.pdf")
    smp = tmp / "cream_scale_smp.pdf"; transform_page(ref, smp, scale=0.985)
    case("NOT SUPPORTED", "NO wording change. Whole artwork scaled to 98.5% (a printer/imposition scaling error). "
                          "Ideal answer: one 'scaled 98.5%' finding; expect many small layout findings instead", ref, smp, ref)

    ref, smp = tmp / "noctura_ref.pdf", tmp / "noctura_smp.pdf"
    rich_black_label(ref, (0, 0, 0, 1)); rich_black_label(smp, (0.6, 0.4, 0.4, 1))
    case("NOT SUPPORTED", "Black panel changed from K-only (0/0/0/100) to rich black (60/40/40/100): looks the same on screen, "
                          "prints differently. True CMYK separation checking is on the roadmap", ref, smp, ref)

    ref, smp = tmp / "spot_ref.pdf", tmp / "spot_smp.pdf"
    spot_label(ref, "PANTONE 286 C", overprint=False)
    spot_label(smp, "PANTONE 287 C", overprint=True)
    case("NOT SUPPORTED (until now)", "Brand band printed in PANTONE 287 C instead of PANTONE 286 C, and set to overprint. "
                                      "Both look identical on screen", ref, smp, ref)

    ref, smp = tmp / "cjk_ref.pdf", tmp / "cjk_smp.pdf"
    cjk_label(ref, "250mg", "注意：肝功能不全者慎用。")
    cjk_label(smp, "500mg", "注意：肝功能不全者禁用。")
    case("NOT SUPPORTED (partly)", 'Chinese label: strength "250mg" -> "500mg", and the warning "慎用" (use with caution) -> "禁用" (do not use). '
                                  "Text diff should see both; spell check and OCR don't cover Chinese", ref, smp, ref)

    order = list(range(len(cases)))
    rng.shuffle(order)
    key = ["ANSWER KEY - open only after you've run every pair.", "",
           "[SHOULD CATCH] within what the tool claims.  [MAY STRUGGLE] near a known limit.  [NOT SUPPORTED] outside today's scope.", ""]
    for i, ci in enumerate(order, 1):
        bucket, what, ref, smp, deck_src = cases[ci]
        tag = f"pair_{i:02d}"
        shutil.copy(ref, OUT / f"{tag}_reference.pdf")
        shutil.copy(smp, OUT / f"{tag}_sample.pdf")
        if deck_src is not None:
            deck_for(deck_src, OUT / f"{tag}_approved_text.docx")
        key.append(f"{tag} [{bucket}]: {what}")
    (OUT / "ANSWER_KEY.txt").write_text("\n".join(key) + "\n", encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"{len(cases)} pairs written to {OUT}. Don't open ANSWER_KEY.txt until you've run them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
