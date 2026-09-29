"""Build the EXTREME showcase -> demo/showcase_extreme/  (harder, messier, closer to real life)

    python make_showcase_extreme.py

Stress scenarios that push the proofer toward its limits: a dense 2-page leaflet with 30 defects, a digit storm,
a 2-up imposed sheet where only one carton is wrong, a swapped-page leaflet, low-resolution scans, an
"everything at once" file, and a phone photo. Some are meant to be beaten. The scorecard says which, and the
folder names carry a tag: [STRONG], [STRESS] or [LIMIT] so you know what to expect before you show it.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pymupdf

import make_showcase as ms
from make_hard import phone_photo, transform_page
from mutate import flatten

ROOT = Path(__file__).parent
S = ROOT / "samples"
OUT = ROOT / "demo" / "showcase_extreme"
MM = 72 / 25.4
DIGITS = ["digit_change", "digit_swap", "decimal_drop"]


def imposed_sheet(single: Path, dst: Path, right_src: Path | None = None):
    """Two copies of a carton side by side on one sheet with crop marks; the right copy may come from another file."""
    s = pymupdf.open(single)
    r = s[0].rect
    gap, m = 30, 30
    W, H = 2 * r.width + gap + 2 * m, r.height + 2 * m
    out = pymupdf.open()
    pg = out.new_page(width=W, height=H)
    pg.show_pdf_page(pymupdf.Rect(m, m, m + r.width, m + r.height), s, 0)
    rs = pymupdf.open(right_src or single)
    x2 = m + r.width + gap
    pg.show_pdf_page(pymupdf.Rect(x2, m, x2 + r.width, m + r.height), rs, 0)
    for x in (m, m + r.width, x2, x2 + r.width):          # crop marks
        for y in (m, m + r.height):
            pg.draw_line((x - 10, y), (x - 3, y), width=0.4)
            pg.draw_line((x, y - 10), (x, y - 3), width=0.4)
    out.save(dst)
    return x2


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    ms.OUT = OUT
    tmp = Path(tempfile.mkdtemp())
    T = []
    lf, lf_deck = S / "master_leaflet.pdf", S / "decks" / "leaflet.docx"

    # A. dense two-page leaflet, 30 different defects
    smp = tmp / "leaf30.pdf"
    key = ms.inject(lf, smp, 30, seed=11)
    ms.run_pair("01_STRESS_leaflet_30_defects", lf, smp, key, lf_deck, False,
                f"2-page, ~500-word leaflet with {len(key)} defects at once", T, None)

    # B. digit storm: only numbers change, 20 of them
    smp = tmp / "digits.pdf"
    key = ms.inject(lf, smp, 20, seed=21, only=DIGITS)
    ms.run_pair("02_STRONG_digit_storm", lf, smp, key, lf_deck, False,
                f"{len(key)} number changes (digits, swaps, dropped decimals) buried in dense text", T, None)

    # C. imposed 2-up sheet: only the right-hand carton is wrong, left must stay clean
    bad = tmp / "carton_bad.pdf"
    key = ms.inject(S / "master_carton.pdf", bad, 8, seed=31)
    ref = tmp / "sheet_ref.pdf"
    smp = tmp / "sheet_smp.pdf"
    imposed_sheet(S / "master_carton.pdf", ref)
    x2 = imposed_sheet(S / "master_carton.pdf", smp, right_src=bad)
    for k in key:                                       # move each defect region onto the right-hand carton
        r = k["region"]
        k["region"] = [r[0] + x2, r[1] + 30, r[2] + x2, r[3] + 30]
    ms.run_pair("03_STRESS_imposed_2up_sheet", ref, smp, key, None, False,
                f"2-up imposed sheet with crop marks: {len(key)} defects, all on the RIGHT carton only", T, None)

    # D. leaflet pages swapped AND defects
    smp = tmp / "leaf_swap.pdf"
    key = ms.inject(lf, tmp / "leaf_bad.pdf", 8, seed=41)
    d = pymupdf.open(tmp / "leaf_bad.pdf")
    d.select([1, 0])
    d.save(smp)
    ms.run_pair("04_STRESS_pages_swapped_plus_defects", lf, smp, key, lf_deck, False,
                f"Pages in the wrong order, plus {len(key)} defects inside them", T, None, loose_page=True)

    # E. re-imposed + 20 defects + flattened at 300 dpi
    a = tmp / "e_bad.pdf"
    key = ms.inject(lf, a, 20, seed=51)
    b, c = tmp / "e_reimp.pdf", tmp / "e_flat.pdf"
    transform_page(a, b, dx=1.0 * MM, dy=-0.7 * MM, scale=0.985)
    flatten(str(b), str(c), dpi=300)
    ms.run_pair("05_LIMIT_everything_at_once", lf, c, key, lf_deck, True,
                f"{len(key)} defects, whole file scaled 98.5% and shifted, AND flattened to a picture", T, None, loose_page=True)

    # F. low-resolution scans of a defective leaflet
    a = tmp / "lowres_bad.pdf"
    key = ms.inject(lf, a, 12, seed=61)
    for dpi in (200, 100):
        c = tmp / f"lowres_{dpi}.pdf"
        flatten(str(a), str(c), dpi=dpi)
        ms.run_pair(f"06_{'STRESS' if dpi == 200 else 'LIMIT'}_flattened_{dpi}dpi", lf, c, key, lf_deck, True,
                    f"{len(key)} defects, sample supplied as a {dpi} dpi picture (small print will suffer)", T, None)

    # G. phone photo of a defective carton: the tool should say it cannot compare reliably
    a, c = tmp / "ph_bad.pdf", tmp / "ph.pdf"
    key = ms.inject(S / "master_carton.pdf", a, 6, seed=71)
    phone_photo(a, c, seed=3)
    ms.run_pair("07_LIMIT_phone_photo", S / "master_carton.pdf", c, [], S / "decks" / "carton.docx", True,
                "A tilted, blurry phone photo of a defective carton. Expect a coverage warning, not a clean read", T, None)

    # H. rotation only (content identical)
    a, c = tmp / "rot_in.pdf", tmp / "rot.pdf"
    d = pymupdf.open(lf)
    d.save(c)
    d2 = pymupdf.open(c)
    d2[0].set_rotation(90)
    d2.save(tmp / "rot90.pdf")
    ms.run_pair("08_STRONG_page_rotated", lf, tmp / "rot90.pdf", [], lf_deck, False,
                "Same content, first page rotated 90 degrees in the file", T, None)

    inj, fnd = sum(t[1] for t in T), sum(t[2] for t in T)
    rows = ["# Extreme showcase results", "",
            f"**{fnd} of {inj} injected defects found** across {len(T)} proofs. STRONG = expected to do well, STRESS = hard, LIMIT = expected to struggle or warn.", "",
            "| Proof | Injected | Found | Extra findings | Verdict | What it is |", "|---|---|---|---|---|---|"]
    rows += [f"| [{t[0]}]({t[0]}/report.html) | {t[1] or '-'} | {t[2] if t[1] else '-'} | {t[3]} | {t[4]} | {t[5]} |" for t in T]
    rows += ["", "Read the LIMIT rows out loud in the demo: showing where it stops is what makes the other numbers believable.",
             "Fictional packs; the tool was tuned on the base designs. Rebuild with `python make_showcase_extreme.py`."]
    (OUT / "SCORECARD.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{fnd}/{inj} injected defects found in {len(T)} proofs -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
