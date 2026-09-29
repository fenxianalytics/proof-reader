"""Batch proofing from the command line.

    python -m proofer.batch FOLDER [-o OUT] [--workers 2] [--dpi 300]

Pairs every reference / sample (/ approved text) in FOLDER by name (see proofer/pairing.py), proofs each pair,
and writes OUT/<pair>.html plus OUT/summary.csv and OUT/findings.csv. Exit code 1 if any proof FAILs.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .pairing import pair


def _one(job):
    folder, g, out, dpi = job
    from .compare import compare
    from .report import build_html, sha256
    ref, smp = folder / g["ref"], folder / g["sample"]
    deck = folder / g["deck"] if g.get("deck") else None
    from . import profiles
    settings = profiles.load()
    cfg = profiles.make_config(settings, dpi=dpi)
    t0 = time.time()
    try:
        res = compare(str(ref), str(smp), cfg, keep_images=True, deck=str(deck) if deck else None, settings=settings)
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the batch
        return dict(key=g["key"], error=str(exc) or exc.__class__.__name__)
    meta = dict(sha256=dict(ref=sha256(ref), sample=sha256(smp)))
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in g["key"])[:60]
    (out / f"{safe}.html").write_text(build_html(res, ref.name, smp.name, cfg=cfg, meta=meta, deck_name=deck.name if deck else ""), encoding="utf-8")
    d = res.to_dict()
    return dict(key=g["key"], ref=g["ref"], sample=g["sample"], deck=g.get("deck") or "", verdict=res.verdict, counts=d["counts"],
                limited=res.coverage_limited, seconds=round(time.time() - t0, 1), report=f"{safe}.html",
                findings=[f for f in d["findings"] if f["severity"] != "info"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="proofer.batch", description="Proof every reference/sample pair in a folder.")
    ap.add_argument("folder")
    ap.add_argument("-o", "--out", default=None, help="output folder (default: FOLDER/proofs)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--dpi", type=int, default=300)
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    folder = Path(args.folder)
    out = Path(args.out) if args.out else folder / "proofs"
    out.mkdir(parents=True, exist_ok=True)
    files = [p.relative_to(folder).as_posix() for p in folder.rglob("*")
             if p.is_file() and p.suffix.lower() in (".pdf", ".jpg", ".jpeg", ".png", ".docx", ".txt") and out not in p.parents]
    plan = pair(files)
    print(f"{len(plan['pairs'])} pairs, {len(plan['unpaired'])} unpaired file(s)")
    for u in plan["unpaired"]:
        print(f"  not paired: {u}")
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(_one, [(folder, g, out, args.dpi) for g in plan["pairs"]]):
            rows.append(r)
            if "error" in r:
                print(f"  ERROR   {r['key']}: {r['error']}")
            else:
                c = r["counts"]
                print(f"  {r['verdict']:6}  {r['key']:40} {c['critical']}c {c['major']}M {c['minor']}m  {r['seconds']}s")
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pair", "reference", "sample", "approved_text", "verdict", "critical", "major", "minor", "coverage_limited", "report"])
        for r in rows:
            c = r.get("counts", {})
            w.writerow([r["key"], r.get("ref", ""), r.get("sample", ""), r.get("deck", ""), r.get("verdict", "ERROR"),
                        c.get("critical", ""), c.get("major", ""), c.get("minor", ""), r.get("limited", ""), r.get("report", r.get("error", ""))])
    with open(out / "findings.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pair", "id", "page", "severity", "confidence", "category", "kind", "message", "reference", "sample"])
        for r in rows:
            for f in r.get("findings", []):
                w.writerow([r["key"], f["id"], f["page"] + 1, f["severity"], f["confidence"], f["category"], f["kind"], f["message"], f["a_text"], f["b_text"]])
    fails = sum(r.get("verdict") == "FAIL" for r in rows)
    print(f"-> {out}   ({fails} FAIL, {sum(r.get('verdict') == 'REVIEW' for r in rows)} REVIEW, {sum(r.get('verdict') == 'PASS' for r in rows)} PASS)")
    return 1 if fails or any("error" in r for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
