"""Mutation testing: inject KNOWN defects into any PDF and measure how many the proofer catches.

    python mutate.py                       # the built-in masters plus anything in real/
    python mutate.py real/*.pdf --per 6    # your own artwork, 6 mutants of each kind per file
    python mutate.py --seed 7 --workers 4

Why this exists: the hand-built samples/answer_key.json was written by the same person who tuned the
tool. This takes ANY reference PDF (drop the client's real, approved artwork in real/) and derives
hundreds of defective samples from it automatically, so recall is measured on artwork the tuning
never saw. Each mutant is also flattened to pixels ("image-only" artwork), the harder path.

Reported per defect type: recall, and the exact 95% upper bound on the true miss rate (with 0 misses in
n trials that is 1 - 0.05**(1/n): ~3% at n=100). That bound, not "100%", is the honest claim.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pymupdf

ROOT = Path(__file__).parent
MM = 72 / 25.4
PDF_REDACT_IMAGE_REMOVE = 1

LIVE_TEXT = ["text"]
TEXT_MUTS = ("digit_change", "digit_swap", "decimal_drop", "unit_change", "typo", "word_delete")
DECKS = dict(master="syrup", master_carton="carton", master_vial="vial", master_tube="tube", master_leaflet="leaflet", master_blister="blister")


def _deck_for(src: str) -> str | None:
    d = DECKS.get(Path(src).stem)
    p = ROOT / "samples" / "decks" / f"{d}.docx" if d else Path(src).with_suffix(".docx")
    return str(p) if p.exists() else None
ANY_VISIBLE = ["graphic", "layout", "color", "text", "format", "barcode"]


# ── helpers ───────────────────────────────────────────────────────────────
def _spans(page):
    out = []
    for blk in page.get_text("dict")["blocks"]:
        for ln in blk.get("lines", []):
            for sp in ln["spans"]:
                if sp["text"].strip():
                    out.append(sp)
    return out


def _word_style(page, w):
    cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
    for sp in _spans(page):
        b = sp["bbox"]
        if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]:
            return sp
    return None


def _rgb(c):
    return ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255)


def _erase(page, rect, images=0):
    page.add_redact_annot(pymupdf.Rect(rect), fill=False)
    page.apply_redactions(images=images, graphics=0)


def _base14(font: str) -> str:
    """Closest built-in font to the one the word was set in, so an injected edit doesn't also change the font."""
    f, bold, ital = font.lower(), "bold" in font.lower(), ("italic" in font.lower() or "oblique" in font.lower())
    if "courier" in f:
        return "cobo" if bold else "cour"
    if "times" in f or "serif" in f and "sans" not in f:
        return "tibo" if bold else "tiit" if ital else "tiro"
    return "hebo" if bold else "heit" if ital else "helv"


def _put(page, word, x, sp, dy=0.0):
    fs = sp["size"]
    page.insert_text((x, sp["origin"][1] + dy), word, fontsize=fs, fontname=_base14(sp["font"]), color=_rgb(sp["color"]))


def _pad(r, p):
    return [r[0] - p, r[1] - p, r[2] + p, r[3] + p]


def _union(a, b):
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _candidates(page, pred):
    ws = [w for w in page.get_text("words") if pred(w[4]) and (w[2] - w[0]) > 2 and (w[3] - w[1]) > 3]
    return [(w, sp) for w in ws for sp in [_word_style(page, w)] if sp]


def _shrink(w):
    return [w[0] + 0.4, w[1] + 0.4, w[2] - 0.4, w[3] - 0.4]


# ── mutators: each edits `page` in place, returns (description, region, expected_categories, min_severity) or None ──
def m_digit_change(page, rng):
    c = _candidates(page, lambda t: re.search(r"\d", t))
    if not c:
        return None
    w, sp = rng.choice(c)
    t = w[4]
    i = rng.choice([k for k, ch in enumerate(t) if ch.isdigit()])
    new = t[:i] + rng.choice([d for d in "0123456789" if d != t[i]]) + t[i + 1:]
    _erase(page, _shrink(w))
    _put(page, new, w[0], sp)
    return f'digit change "{t}" -> "{new}"', list(w[:4]), LIVE_TEXT + ["barcode"], "critical"


def m_digit_swap(page, rng):
    c = _candidates(page, lambda t: len(re.findall(r"\d", t)) >= 2 and len(set(re.findall(r"\d", t))) >= 2)
    if not c:
        return None
    w, sp = rng.choice(c)
    t = w[4]
    pos = [k for k, ch in enumerate(t) if ch.isdigit()]
    for _ in range(20):
        a, b = rng.sample(pos, 2)
        if t[a] != t[b]:
            break
    else:
        return None
    L = list(t); L[a], L[b] = L[b], L[a]
    new = "".join(L)
    _erase(page, _shrink(w))
    _put(page, new, w[0], sp)
    return f'digits swapped "{t}" -> "{new}"', list(w[:4]), LIVE_TEXT + ["barcode"], "critical"


def m_word_delete(page, rng):
    c = _candidates(page, lambda t: len(t) >= 3)
    if not c:
        return None
    w, sp = rng.choice(c)
    _erase(page, _shrink(w))
    return f'word deleted "{w[4]}"', list(w[:4]), LIVE_TEXT + ["graphic"], "minor"


def m_typo(page, rng):
    c = _candidates(page, lambda t: len(t) >= 5 and t.isalpha())
    if not c:
        return None
    w, sp = rng.choice(c)
    t = w[4]
    i = rng.randrange(1, len(t) - 2)
    if t[i] == t[i + 1]:
        return None
    new = t[:i] + t[i + 1] + t[i] + t[i + 2:]
    _erase(page, _shrink(w))
    _put(page, new, w[0], sp)
    return f'transposed letters "{t}" -> "{new}"', list(w[:4]), LIVE_TEXT, "minor"


def m_unit_change(page, rng):
    c = _candidates(page, lambda t: t.lower() in ("mg", "ml", "mcg", "g", "µg", "iu"))
    if not c:
        return None
    w, sp = rng.choice(c)
    swap = {"mg": "mcg", "ml": "mg", "mcg": "mg", "g": "mg", "µg": "mg", "iu": "mg"}[w[4].lower()]
    _erase(page, _shrink(w))
    _put(page, swap, w[0], sp)
    return f'unit changed "{w[4]}" -> "{swap}"', list(w[:4]), LIVE_TEXT, "critical"


def m_text_shift(page, rng):
    c = _candidates(page, lambda t: len(t) >= 4)
    if not c:
        return None
    w, sp = rng.choice(c)
    d = rng.uniform(1.2, 3.5) * MM
    dx, dy = rng.choice([(d, 0), (-d, 0), (0, d), (0, -d)])
    _erase(page, _shrink(w))
    _put(page, w[4], w[0] + dx, sp, dy)
    moved = [w[0] + dx, w[1] + dy, w[2] + dx, w[3] + dy]
    return f'word "{w[4]}" moved {d / MM:.1f} mm', _union(list(w[:4]), moved), ANY_VISIBLE, "minor"


def m_image_remove(page, rng):
    imgs = [i for i in page.get_image_info() if (i["bbox"][2] - i["bbox"][0]) > 12 and (i["bbox"][3] - i["bbox"][1]) > 12]
    if not imgs:
        return None
    im = rng.choice(imgs)
    _erase(page, im["bbox"], images=PDF_REDACT_IMAGE_REMOVE)
    return "image removed", list(im["bbox"]), ["graphic", "layout", "structure", "color"], "minor"


def m_recolor(page, rng):
    words = [w[:4] for w in page.get_text("words")]
    shapes = []
    for d in page.get_drawings():
        r, fill = d.get("rect"), d.get("fill")
        if fill is None or r is None or r.is_empty or r.width < 6 or r.height < 6 or r.width * r.height > 20000:
            continue
        if any(pymupdf.Rect(w).intersects(r) for w in words):
            continue  # an overlay would hide the text; use plain shapes only
        shapes.append((r, fill))
    if not shapes:
        return None
    r, fill = rng.choice(shapes)
    ch = rng.randrange(3)
    new = list(fill)
    new[ch] = min(1.0, new[ch] + 0.09) if new[ch] < 0.9 else new[ch] - 0.09
    page.draw_rect(r, color=None, fill=tuple(new))
    return "shape recoloured by ~9/255 in one channel", [r.x0, r.y0, r.x1, r.y1], ["color", "graphic"], "minor"


def m_stray_mark(page, rng):
    words = [pymupdf.Rect(w[:4]) for w in page.get_text("words")]
    r = page.rect
    for _ in range(60):
        s = rng.uniform(0.5, 1.2) * MM
        x, y = rng.uniform(r.x0 + 15, r.x1 - 15), rng.uniform(r.y0 + 15, r.y1 - 15)
        box = pymupdf.Rect(x, y, x + s, y + s)
        if not any((wd + (-3, -3, 3, 3)).intersects(box) for wd in words) and not any(d["rect"].intersects(box) for d in page.get_drawings() if d.get("rect")):
            page.draw_circle((x + s / 2, y + s / 2), s / 2, color=None, fill=(0, 0, 0))
            return f"stray {s / MM:.1f} mm mark", [x, y, x + s, y + s], ["graphic"], "minor"
    return None


def m_decimal_drop(page, rng):
    c = _candidates(page, lambda t: re.fullmatch(r"\d+[.,]\d+", t))
    if not c:
        return None
    w, sp = rng.choice(c)
    new = re.sub(r"[.,]", "", w[4])
    _erase(page, _shrink(w))
    _put(page, new, w[0], sp)
    return f'decimal point dropped "{w[4]}" -> "{new}"', list(w[:4]), LIVE_TEXT, "critical"


MUTATORS = dict(digit_change=m_digit_change, digit_swap=m_digit_swap, decimal_drop=m_decimal_drop, unit_change=m_unit_change,
                typo=m_typo, word_delete=m_word_delete, text_shift=m_text_shift, image_remove=m_image_remove,
                recolor=m_recolor, stray_mark=m_stray_mark)


def flatten(src: str, dst: str, dpi: int = 300) -> None:
    doc = pymupdf.open(src)
    out = pymupdf.open()
    for pg in doc:
        pix = pg.get_pixmap(dpi=dpi, alpha=False)
        np_ = out.new_page(width=pg.rect.width, height=pg.rect.height)
        np_.insert_image(np_.rect, pixmap=pix)
    out.save(dst)


# ── one trial (runs in a worker process) ──────────────────────────────────
def _trial(job):
    src, mut, seed, flat, keep_dir = job
    from proofer import Config, compare
    from proofer.compare import SEV_RANK, _inter
    rng = random.Random(seed)
    with tempfile.TemporaryDirectory() as td:
        doc = pymupdf.open(src)
        pno = rng.randrange(len(doc))
        res = MUTATORS[mut](doc[pno], rng) if mut != "control" else ("no change", None, [], "info")
        if res is None:
            return dict(src=Path(src).name, mut=mut, flat=flat, skipped=True)
        desc, region, expected, min_sev = res
        mutated = os.path.join(td, "m.pdf")
        doc.save(mutated, garbage=1)
        sample = mutated
        if flat:
            sample = os.path.join(td, "f.pdf")
            flatten(mutated, sample)
        deck = _deck_for(src)
        r = compare(src, sample, Config(), keep_images=False, deck=deck)
        real = [f for f in r.findings if f.severity != "info" and (f.page == pno or region is None)]
        row = dict(src=Path(src).name, mut=mut, flat=flat, page=pno, desc=desc, verdict=r.verdict, skipped=False)
        if region is None:  # a control: must stay silent
            row.update(kind="control", false_alarm=bool([f for f in r.findings if f.severity != "info"]),
                       got=[f"{f.severity} {f.category}/{f.kind}: {f.message[:90]}" for f in r.findings if f.severity != "info"])
            return row
        zone = _pad(region, 4.0)
        hits = [f for f in real if any(b and _inter(b, zone) > 0 for b in (f.bbox_a, f.bbox_b))]
        exp = ["graphic", "layout", "color", "structure"] if flat and "text" in expected else expected
        good = [f for f in hits if f.category in exp or (flat and f.category in ("graphic", "layout", "color", "text", "barcode"))]
        sev_ok = any(SEV_RANK[f.severity] >= SEV_RANK[min_sev] for f in good)
        # digits printed as a barcode's caption are verified by the barcode check, not the approved-text check
        deck_ok = deck and not re.search(r'"\d+"', desc)
        # the approved-text check counts whether it reported on its own or confirmed (and was merged into) another finding
        deck_hit = any((f.category == "copydeck" or "approved_text" in f.detail) and SEV_RANK[f.severity] >= SEV_RANK[min_sev]
                       and any(r and _inter(r, zone) > 0 for r in (f.bbox_b, f.bbox_a)) for f in real) if deck_ok else None
        row.update(kind="defect", region=region, deck_hit=deck_hit, detected=bool(hits), classified=bool(good), severity_ok=sev_ok,
                   verdict_ok=r.verdict != "PASS", got=[f"{f.severity} {f.category}/{f.kind}" for f in hits])
        if keep_dir and not (good and sev_ok):
            Path(keep_dir).mkdir(parents=True, exist_ok=True)
            tag = f"{Path(src).stem}_{mut}_{seed}{'_flat' if flat else ''}"
            Path(keep_dir, tag + ".pdf").write_bytes(Path(sample).read_bytes())
            row["kept"] = tag + ".pdf"
        return row


def upper_miss_bound(misses: int, n: int, conf: float = 0.95) -> float:
    """One-sided exact (Clopper-Pearson) upper confidence bound on the true miss rate."""
    if n == 0:
        return 1.0
    if misses >= n:
        return 1.0
    from scipy.stats import beta
    return float(beta.ppf(conf, misses + 1, n - misses))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="*", help="reference PDFs to mutate (default: samples/master*.pdf and real/*.pdf)")
    ap.add_argument("--per", type=int, default=3, help="mutants per defect type per PDF (default 3)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--no-flat", action="store_true", help="skip the flattened (image-only) variant of each mutant")
    ap.add_argument("--only", help="comma-separated mutation names")
    ap.add_argument("--keep", default=str(ROOT / "results" / "missed"), help="save samples for every miss here")
    ap.add_argument("--out", default=str(ROOT / "results" / "mutation.json"))
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    pdfs = args.pdfs or sorted(str(p) for p in list((ROOT / "samples").glob("master*.pdf")) + list((ROOT / "real").glob("*.pdf")))
    muts = args.only.split(",") if args.only else list(MUTATORS)
    jobs = []
    for pi, src in enumerate(pdfs):
        for mi, mut in enumerate(muts):
            for k in range(args.per):
                for flat in ([False] if args.no_flat else [False, True]):
                    jobs.append((src, mut, args.seed * 100003 + pi * 1009 + mi * 101 + k, flat, args.keep))
        for flat in ([False] if args.no_flat else [False, True]):
            jobs.append((src, "control", 0, flat, None))
    print(f"{len(pdfs)} PDFs, {len(jobs)} trials, {args.workers} workers")
    t0 = time.time()
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for i, r in enumerate(ex.map(_trial, jobs, chunksize=1), 1):
            rows.append(r)
            if i % 20 == 0:
                print(f"  {i}/{len(jobs)}  ({time.time() - t0:.0f}s)", flush=True)
    done = [r for r in rows if not r["skipped"]]
    defects = [r for r in done if r["kind"] == "defect"]
    controls = [r for r in done if r["kind"] == "control"]

    def line(name, rs):
        n = len(rs)
        if not n:
            return None
        miss = sum(not (r["classified"] and r["severity_ok"]) for r in rs)
        det = sum(r["detected"] for r in rs)
        return dict(name=name, n=n, detected=det, ok=n - miss, misses=miss, recall=(n - miss) / n, miss_upper95=upper_miss_bound(miss, n))

    table = []
    print(f"\n{'defect type':16} {'mode':11} {'n':>4} {'caught':>7} {'recall':>8}  95% upper bound on miss rate")
    for mut in muts:
        for flat in ([False] if args.no_flat else [False, True]):
            ln = line(mut, [r for r in defects if r["mut"] == mut and r["flat"] == flat])
            if ln:
                ln["mode"] = "image-only" if flat else "live text"
                table.append(ln)
                print(f"{mut:16} {ln['mode']:11} {ln['n']:>4} {ln['ok']:>7} {ln['recall']:>8.1%}  <= {ln['miss_upper95']:.1%}")
    tot = line("ALL", defects)
    if tot:
        print(f"{'ALL':16} {'':11} {tot['n']:>4} {tot['ok']:>7} {tot['recall']:>8.1%}  <= {tot['miss_upper95']:.1%}")
    dk = [r for r in defects if r["mut"] in TEXT_MUTS and r.get("deck_hit") is not None]
    if dk:
        print("\ncopy-deck check alone (approved text vs sample), text defects:")
        for flat in (False, True):
            rs = [r for r in dk if r["flat"] == flat]
            if rs:
                ok = sum(r["deck_hit"] for r in rs)
                print(f"  {'image-only (OCR)' if flat else 'live text':17} {ok}/{len(rs)} = {ok / len(rs):.1%}   miss rate <= {upper_miss_bound(len(rs) - ok, len(rs)):.1%}")
                table.append(dict(name="copy deck", mode="image-only" if flat else "live text", n=len(rs), ok=ok, detected=ok, misses=len(rs) - ok,
                                  recall=ok / len(rs), miss_upper95=upper_miss_bound(len(rs) - ok, len(rs))))
    fa = [c for c in controls if c["false_alarm"]]
    print(f"\ncontrols (identical / flattened copy of the same file): {len(fa)} false alarms in {len(controls)}")
    for c in fa:
        print(f"  {c['src']} flat={c['flat']}: {c['got'][:3]}")
    missed = [r for r in defects if not (r["classified"] and r["severity_ok"])]
    print(f"\nmisses: {len(missed)}   (samples saved to {args.keep})" if missed else "\nno misses")
    for r in missed[:40]:
        print(f"  {r['src']:22} {r['mut']:13} {'flat' if r['flat'] else 'live'}  {r['desc'][:55]:55} got={r['got'] or 'NOTHING'}")
    Path(args.out).parent.mkdir(exist_ok=True)
    Path(args.out).write_text(json.dumps(dict(seed=args.seed, per=args.per, table=table, total=tot, controls=dict(n=len(controls), false_alarms=len(fa)),
                                              rows=rows, skipped=sum(r["skipped"] for r in rows), measured=time.strftime("%Y-%m-%d %H:%M")), indent=1, default=str), encoding="utf-8")
    return 1 if missed or fa else 0


if __name__ == "__main__":
    sys.exit(main())
