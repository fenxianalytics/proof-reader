"""Build the client demo pack: one offline HTML proof report per scenario, plus the talk track.

    python make_decks.py     # once
    python make_demo.py      # writes demo/*.html and demo/DEMO_SCRIPT.md

Each report is a single self-contained file (no server, no internet), so the demo still works if the laptop
is offline or the app won't start.
"""
from __future__ import annotations

import random
import shutil
import sys
import tempfile
from pathlib import Path

import pymupdf

from proofer import compare, profiles
from proofer.copydeck import load_deck, write_docx
from proofer.report import build_html, sha256

ROOT = Path(__file__).parent
S = ROOT / "samples"
OUT = ROOT / "demo"


def _typo_variant(dst: Path) -> None:
    """The syrup label with two letters transposed in one word - the classic proofreading miss."""
    from mutate import _erase, _rgb, _word_style
    doc = pymupdf.open(S / "master.pdf")
    pg = doc[0]
    w = next(w for w in pg.get_text("words") if w[4] == "Suspension")
    sp = _word_style(pg, w)
    _erase(pg, [w[0] + 0.4, w[1] + 0.4, w[2] - 0.4, w[3] - 0.4])
    pg.insert_text((w[0], sp["origin"][1]), "Suspnesion", fontsize=sp["size"], color=_rgb(sp["color"]),
                   fontname="hebo" if "Bold" in sp["font"] else "helv")
    doc.save(dst)


def _updated_deck(dst: Path) -> None:
    """Approved text that was revised (storage 25 -> 30 °C) after the artwork was made: the artwork is now wrong."""
    paras = [p.replace("25 °C", "30 °C") for p in load_deck(str(S / "decks" / "syrup.docx"))]
    write_docx(paras, str(dst))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not (S / "decks" / "syrup.docx").exists():
        print("run python make_decks.py first")
        return 2
    OUT.mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    _typo_variant(tmp / "syrup_typo.pdf")
    _updated_deck(tmp / "syrup_approved_text_rev2.docx")
    from make_hard import replace_word, rich_black_label, spot_label, transform_page
    d0 = pymupdf.open(S / "master.pdf")
    replace_word(d0[0], "5-11", "6-11") or replace_word(d0[0], "6-11", "5-11")
    d0.save(tmp / "syrup_edit.pdf")
    transform_page(tmp / "syrup_edit.pdf", tmp / "syrup_reimposed.pdf", dx=1.2 * 72 / 25.4, dy=-0.8 * 72 / 25.4, scale=0.99)
    spot_label(tmp / "spot_ref.pdf", "PANTONE 286 C", overprint=False)
    spot_label(tmp / "spot_smp.pdf", "PANTONE 287 C", overprint=True)
    rich_black_label(tmp / "black_ref.pdf", (0, 0, 0, 1))
    rich_black_label(tmp / "black_smp.pdf", (0.6, 0.4, 0.4, 1))
    d = S / "decks"
    scenarios = [
        ("01_dose_change", "master.pdf", "variants/dose_digits_swapped.pdf", d / "syrup.docx",
         "Strength printed as 152 mg instead of 125 mg.",
         "Caught twice, independently: against the approved artwork AND against the approved text. Critical, because digits changed."),
        ("02_flattened_artwork", "master.pdf", "variants/imageonly_dose_digits_swapped.pdf", d / "syrup.docx",
         "Same error, but the supplier sent flattened (image-only) artwork with no text layer.",
         "Most tools go blind here. We read it with OCR, flag it critical, and say plainly that coverage was limited."),
        ("03_braille", "master_carton.pdf", "variants/carton_braille_error.pdf", d / "carton.docx",
         "One braille cell wrong on the carton.",
         "Braille is decoded to letters on both files: 'lumexa' vs 'xumexa'. Not a pixel diff - a meaning diff."),
        ("04_barcode", "master.pdf", "variants/barcode_bars_changed_digits_same.pdf", d / "syrup.docx",
         "The bars were changed but the printed digits under them were not.",
         "Barcodes are decoded and cross-checked against their own printed number. A visual check can't see this."),
        ("05_varnish_layer", "master_carton.pdf", "variants/carton_varnish_layer_off.pdf", d / "carton.docx",
         "The spot-varnish layer was switched off in the file.",
         "Read from the PDF structure itself. Nothing looks different on screen, the press would print it wrong."),
        ("06_typo", "master.pdf", str(tmp / "syrup_typo.pdf"), d / "syrup.docx",
         "'Suspension' typed as 'Suspnesion'.",
         "Word-level change, cross-checked by the approved text and flagged as a possible misspelling."),
        ("07_text_revision", "master.pdf", "master.pdf", tmp / "syrup_approved_text_rev2.docx",
         "Artwork unchanged, but the approved text was revised (store below 30 °C).",
         "PDF-vs-PDF says identical; the approved-text check catches that the artwork is now out of date."),
        ("09_reimposed_file", "master.pdf", str(tmp / "syrup_reimposed.pdf"), d / "syrup.docx",
         "The printer re-imposed the file (scaled 99%, shifted) AND one age range changed.",
         "Other tools drown this in hundreds of 'moved' marks. We report the scaling once, line the file up, and show the one real change."),
        ("10_spot_colour", str(tmp / "spot_ref.pdf"), str(tmp / "spot_smp.pdf"), None,
         "Brand colour swapped from PANTONE 286 C to 287 C and set to overprint.",
         "Looks identical on screen. We read the inks and overprint flags from the file itself."),
        ("11_rich_black", str(tmp / "black_ref.pdf"), str(tmp / "black_smp.pdf"), None,
         "K-only black panel rebuilt as rich black (60/40/40/100).",
         "Each CMYK plate is compared on its own - a press-level check a screen comparison can't do."),
        ("12_print_run", "master.pdf", "variants/expiry_changed.pdf", d / "syrup.docx",
         "New print run: only the expiry date changed (run with the Print run check profile).",
         "Lot and expiry are expected to change between runs, so they're logged as variable data, not flagged. Same file in Standard mode = critical."),
        ("08_clean_pass", "master_carton.pdf", "variants/control_carton_identical.pdf", d / "carton.docx",
         "A correct file, re-exported.",
         "No false alarms: every check ran and came back clean. That matters as much as catching errors."),
    ]
    lines = ["# Demo script", "", "Open each file in a browser (double-click). They work offline.", "",
             "| # | Scenario | What happened | What to say | Verdict |", "|---|---|---|---|---|"]
    scenarios.sort(key=lambda sc: sc[0])
    for name, a, b, deck, what, say in scenarios:
        pa = Path(a) if Path(a).is_absolute() else S / a
        pb = Path(b) if Path(b).is_absolute() else S / b
        settings = dict(profiles.load(), profile="print_run" if name == "12_print_run" else "standard")
        cfg = profiles.make_config(settings)
        res = compare(str(pa), str(pb), cfg, keep_images=True, deck=str(deck) if deck else None, settings=settings)
        meta = dict(sha256=dict(ref=sha256(pa), sample=sha256(pb)) | (dict(deck=sha256(deck)) if deck else {}),
                    config={k: getattr(cfg, k) for k in cfg.__dataclass_fields__})
        html = build_html(res, pa.name, pb.name, cfg=cfg, meta=meta, deck_name=deck.name if deck else "")
        (OUT / f"{name}.html").write_text(html, encoding="utf-8")
        c = res.to_dict()["counts"]
        print(f"{name:22} {res.verdict:6} {c['critical']}c {c['major']}M {c['minor']}m")
        lines.append(f"| {name[:2]} | [{name[3:].replace('_', ' ')}]({name}.html) | {what} | {say} | **{res.verdict}** |")
    lines += ["", "## Close", "",
              "- Everything runs on their machine; artwork never leaves the building.",
              "- Every finding says why it fired, and every proof says what could and could not be checked.",
              "- Reviewer sign-off is logged in a tamper-evident audit trail with file hashes.",
              "- Next step: a 4-6 week pilot on their own approved artwork, measured against an agreed target."]
    (OUT / "DEMO_SCRIPT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
