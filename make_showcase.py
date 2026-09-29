"""Build the showcase demo -> demo/showcase/

    python make_showcase.py

Every pair packs SEVERAL known defects into one file (digit changes, swapped digits, dropped decimals, unit
changes, typos, deleted words, moved text, removed images, recolours, stray marks), then runs the proofer and
scores it: injected vs found. Each pair gets an offline HTML report, an INJECTED_DEFECTS.txt (the answer key), and
the README SHOWCASE_SCRIPT.md gives a running order. Deterministic: same files every run.
"""
from __future__ import annotations

import random
import shutil
import sys
import tempfile
from pathlib import Path

import pymupdf

from mutate import MUTATORS, _pad, flatten
from proofer import Config, compare, profiles
from proofer.compare import _inter
from proofer.copydeck import write_docx
from proofer.report import build_html, sha256

ROOT = Path(__file__).parent
S = ROOT / "samples"
OUT = ROOT / "demo" / "showcase"
ORDER = ["digit_change", "unit_change", "typo", "digit_swap", "decimal_drop", "word_delete",
         "text_shift", "image_remove", "recolor", "stray_mark"]
MASTERS = [("syrup", "master.pdf"), ("carton", "master_carton.pdf"), ("vial", "master_vial.pdf"),
           ("tube", "master_tube.pdf"), ("leaflet", "master_leaflet.pdf"), ("blister", "master_blister.pdf")]


def inject(src: Path, dst: Path, n: int, seed: int, only=None) -> list[dict]:
    """Apply up to n non-overlapping defects of different types; returns the answer key."""
    rng = random.Random(seed)
    doc = pymupdf.open(src)
    key, used = [], []
    types = (only or ORDER) * (n // len(only or ORDER) + 2)
    for mut in types:
        if len(key) >= n:
            break
        for _ in range(12):
            pno = rng.randrange(len(doc))
            # try on a scratch copy of the page state: mutators edit in place, so only accept if no overlap
            snap = doc.tobytes()
            res = MUTATORS[mut](doc[pno], rng)
            if res is None:
                doc = pymupdf.open("pdf", snap)
                continue
            desc, region, expected, min_sev = res
            zone = _pad(region, 4)
            if any(k["page"] == pno and _inter(zone, _pad(k["region"], 4)) > 0 for k in key):
                doc = pymupdf.open("pdf", snap)
                continue
            key.append(dict(type=mut, desc=desc, page=pno, region=region, min_sev=min_sev))
            break
    doc.save(dst, garbage=1)
    return key


def score(res, key, flat: bool, loose_page=False):
    real = [f for f in res.findings if f.severity != "info"]
    found, claimed = [], set()
    for k in key:
        zone = _pad(k["region"], 4)
        hits = [f for f in real if (loose_page or f.page == k["page"]) and any(b and _inter(b, zone) > 0 for b in (f.bbox_a, f.bbox_b))]
        claimed.update(id(f) for f in hits)
        found.append(bool(hits))
    return found, [f for f in real if id(f) not in claimed]


def run_pair(name, ref, smp, key, deck, flat, notes, table, scripts, settings=None, loose_page=False):
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(ref, d / "reference.pdf")
    shutil.copy(smp, d / "sample.pdf")
    if deck:
        shutil.copy(deck, d / "approved_text.docx")
    settings = settings or dict(profiles.load(), profile="standard")
    cfg = profiles.make_config(settings)
    res = compare(str(d / "reference.pdf"), str(d / "sample.pdf"), cfg, keep_images=True,
                  deck=str(d / "approved_text.docx") if deck else None, settings=settings)
    meta = dict(sha256=dict(ref=sha256(d / "reference.pdf"), sample=sha256(d / "sample.pdf")),
                config={k: getattr(cfg, k) for k in cfg.__dataclass_fields__})
    (d / "report.html").write_text(build_html(res, "reference.pdf", "sample.pdf", cfg=cfg, meta=meta,
                                               deck_name="approved_text.docx" if deck else ""), encoding="utf-8")
    real = [f for f in res.findings if f.severity != "info"]
    if key:
        found, extra = score(res, key, flat, loose_page)
        lines = [f"{'FOUND ' if ok else 'MISSED'}  p{k['page'] + 1}  {k['desc']}" for k, ok in zip(key, found)]
        (d / "INJECTED_DEFECTS.txt").write_text(f"{notes}\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
        table.append((name, len(key), sum(found), len(extra), res.verdict, notes))
        print(f"{name:34} {sum(found):2}/{len(key):2} found  {len(extra)} extra  {res.verdict}")
    else:
        table.append((name, 0, 0, len(real), res.verdict, notes))
        print(f"{name:34} {len(real)} findings  {res.verdict}  ({notes[:50]})")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not (S / "decks" / "syrup.docx").exists():
        print("run python make_samples.py && python make_decks.py first")
        return 2
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp())
    table = []
    n = 0

    # 1. every pack design, live text, 10 defects at once
    for design, master in MASTERS:
        n += 1
        smp = tmp / f"{design}_multi.pdf"
        key = inject(S / master, smp, 10, seed=100 + n)
        run_pair(f"{n:02d}_{design}_10_defects_live", S / master, smp, key, S / "decks" / f"{design}.docx", False,
                 f"{design}: {len(key)} different defects injected into one live-text file", table, None)

    # 2. the same, flattened to image-only artwork (the hard path)
    for design, master in MASTERS:
        n += 1
        live = tmp / f"{design}_multi.pdf"
        smp = tmp / f"{design}_multi_flat.pdf"
        flatten(str(live), str(smp))
        key = inject(S / master, tmp / "_x.pdf", 10, seed=100 + (n - len(MASTERS)))  # same defects as above
        run_pair(f"{n:02d}_{design}_10_defects_flattened", S / master, smp, key, S / "decks" / f"{design}.docx", True,
                 f"{design}: same {len(key)} defects, but the sample was sent flattened (no text layer)", table, None)

    # 3. kitchen sink: syrup with 16 defects AND the whole file re-imposed (scaled + shifted)
    n += 1
    ks = tmp / "syrup_sink.pdf"
    key = inject(S / "master.pdf", ks, 16, seed=7)
    d = pymupdf.open(ks)
    from make_hard import transform_page
    ks2 = tmp / "syrup_sink_reimposed.pdf"
    transform_page(ks, ks2, dx=1.2 * 72 / 25.4, dy=-0.8 * 72 / 25.4, scale=0.99)
    # after re-imposition regions move slightly; the 4 mm search zone absorbs a ~1 mm shift
    run_pair(f"{n:02d}_kitchen_sink_reimposed", S / "master.pdf", ks2, key, S / "decks" / "syrup.docx", False,
             "syrup: up to 16 defects AND the whole file scaled 99% and shifted 1.2 mm", table, None)

    # 4. controls: must stay silent
    n += 1
    run_pair(f"{n:02d}_clean_control_carton", S / "master_carton.pdf", S / "variants" / "control_carton_identical.pdf", [],
             S / "decks" / "carton.docx", False, "A correct file, re-exported: must be silent", table, None)

    # 5. things a pixel comparison can't see
    from make_hard import rich_black_label, spot_label
    n += 1
    spot_label(tmp / "s_ref.pdf", "PANTONE 286 C", overprint=False)
    spot_label(tmp / "s_smp.pdf", "PANTONE 287 C", overprint=True)
    run_pair(f"{n:02d}_spot_colour_and_overprint", tmp / "s_ref.pdf", tmp / "s_smp.pdf", [], None, False,
             "PANTONE 286 -> 287 and overprint switched on: identical on screen", table, None)
    n += 1
    rich_black_label(tmp / "b_ref.pdf", (0, 0, 0, 1))
    rich_black_label(tmp / "b_smp.pdf", (0.6, 0.4, 0.4, 1))
    run_pair(f"{n:02d}_rich_black", tmp / "b_ref.pdf", tmp / "b_smp.pdf", [], None, False,
             "K-only black rebuilt as rich black: looks the same, prints differently", table, None)
    for i, (nm, a, b, deck, what) in enumerate([
            ("varnish_layer_off", "master_carton.pdf", "variants/carton_varnish_layer_off.pdf", "carton", "Varnish layer switched off"),
            ("braille_error", "master_carton.pdf", "variants/carton_braille_error.pdf", "carton", "One braille cell wrong"),
            ("barcode_bars_changed", "master.pdf", "variants/barcode_bars_changed_digits_same.pdf", "syrup", "Barcode bars changed, printed digits unchanged")]):
        n += 1
        run_pair(f"{n:02d}_{nm}", S / a, S / b, [], S / "decks" / f"{deck}.docx", False, what, table, None)

    # 6. print-run mode: only the expiry changed
    n += 1
    run_pair(f"{n:02d}_print_run_expiry_only", S / "master.pdf", S / "variants" / "expiry_changed.pdf", [],
             S / "decks" / "syrup.docx", False, "Print-run profile: a changed expiry is expected variable data, not a defect",
             table, None, settings=dict(profiles.load(), profile="print_run"))

    # 7. languages (from language_tests/)
    lt = ROOT / "language_tests"
    if lt.exists():
        for case in ["01_en_vs_ru_wrong_language", "04_en_vs_ar_wrong_language", "10_ru_meaning_reversed", "16_zh_meaning_reversed"]:
            n += 1
            run_pair(f"{n:02d}_lang_{case[3:]}", lt / case / "reference.pdf", lt / case / "sample.pdf", [], None, False,
                     f"Language test: {case[3:].replace('_', ' ')}", table, None)

    inj = sum(t[1] for t in table)
    fnd = sum(t[2] for t in table)
    rows = ["# Showcase results", "", f"**{fnd} of {inj} injected defects found** across {len(table)} proofs.", "",
            "| Proof | Injected | Found | Extra findings | Verdict | What it is |", "|---|---|---|---|---|---|"]
    rows += [f"| [{t[0]}]({t[0]}/report.html) | {t[1] or '-'} | {t[2] if t[1] else '-'} | {t[3]} | {t[4]} | {t[5]} |" for t in table]
    rows += ["", "Each folder has reference.pdf, sample.pdf, an offline report.html, and (for injected pairs) INJECTED_DEFECTS.txt.",
             "Extra findings = findings not on an injected defect: a defect described twice, or normal noise. Check them in the report.",
             "Same files every run (fixed seeds). Rebuild with `python make_showcase.py`."]
    (OUT / "SCORECARD.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{fnd}/{inj} injected defects found in {len(table)} proofs -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
