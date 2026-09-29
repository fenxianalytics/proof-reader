"""Scan benchmark: how well does the proofer handle a PRINT-AND-SCAN sample against the approved PDF?

    python bench_scan.py                 # prints recall and false alarms, writes results/bench_scan.json
    python bench_scan.py --compare results/bench_scan.json   # after a change: what got better / worse

Each sample from the answer key (text / barcode / graphic defects of major or critical weight, single page) is turned
into a SIMULATED scan (rasterised, slightly tilted and shifted, blurred, noisy, JPEG) at two quality levels, and compared
with the approved PDF. Clean scans of every master must come back with nothing serious. Simulated scans are only a proxy:
real scans need to be added before any claim about real-world accuracy.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image

from proofer import Config, compare
from proofer.compare import SEV_RANK, _inter, _pad

ROOT = Path(__file__).parent
S = ROOT / "samples"
LEVELS = {  # dpi, rotation deg, shift px, blur sigma, noise sigma, gain
    "good": dict(dpi=300, rot=0.15, dx=3, dy=-2, blur=0.5, noise=2.0, gain=0.985),
    "rough": dict(dpi=300, rot=0.4, dx=6, dy=-4, blur=0.7, noise=3.0, gain=0.97),
}


def scan(src, dst, dpi, rot, dx, dy, blur, noise, gain, seed=1):
    p = pymupdf.open(src)[0]
    pix = p.get_pixmap(dpi=dpi, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3).astype(np.float32)
    h, w = im.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), rot, 1.0)
    M[0, 2] += dx
    M[1, 2] += dy
    im = cv2.warpAffine(im, M, (w, h), borderValue=(250, 250, 250))
    im = cv2.GaussianBlur(im, (0, 0), blur) * gain + np.random.default_rng(seed).normal(0, noise, im.shape)
    Image.fromarray(np.clip(im, 0, 255).astype(np.uint8)).save(dst, quality=88, dpi=(dpi, dpi))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare")
    a = ap.parse_args()
    key = json.loads((S / "answer_key.json").read_text(encoding="utf-8"))["pairs"]
    defects = [p for p in key if p["kind"] == "defect" and p["a"].startswith("master") and "imageonly" not in p["b"] and "flatten" not in p["name"]
               and all(d["page"] == 0 and d["region"] and d["expected_categories"][0] in ("text", "barcode", "graphic") and SEV_RANK[d["min_severity"]] >= 2 for d in p["defects"])]
    masters = sorted({p["a"] for p in key if p["a"].startswith("master") and "imageonly" not in p["a"] and len(pymupdf.open(S / p["a"])) == 1})
    defects = [p for p in defects if p["a"] in masters]  # a single scanned page can't stand in for a multi-page file
    tmp = Path(tempfile.mkdtemp())
    res = {}
    for lvl, prm in LEVELS.items():
        for m in masters:                       # clean scans: must stay quiet
            scan(S / m, tmp / "s.jpg", **prm)
            r = compare(str(S / m), str(tmp / "s.jpg"), Config(), keep_images=False)
            bad = [f"{f.severity} {f.category}/{f.kind}" for f in r.findings if f.severity != "info" and SEV_RANK[f.severity] >= 2 and f.kind != "page_transform"]
            res[f"{lvl}|clean|{m}"] = dict(kind="clean", ok=not bad, verdict=r.verdict, extra=bad)
        for p in defects:                       # defective scans: the real change must be reported
            scan(S / p["b"], tmp / "s.jpg", **prm)
            r = compare(str(S / p["a"]), str(tmp / "s.jpg"), Config(), keep_images=False)
            real = [f for f in r.findings if f.severity != "info" and f.kind != "page_transform"]
            hit = [any(any(b and _inter(b, _pad(d["region"], 6)) > 0 for b in (f.bbox_a, f.bbox_b)) for f in real) for d in p["defects"]]
            spurious = [f"{f.severity} {f.category}/{f.kind}" for f in real if SEV_RANK[f.severity] >= 2 and not any(b and any(_inter(b, _pad(d["region"], 6)) > 0 for d in p["defects"]) for b in (f.bbox_a, f.bbox_b))]
            res[f"{lvl}|defect|{p['name']}"] = dict(kind="defect", ok=all(hit), found=sum(hit), of=len(hit), verdict=r.verdict, extra=spurious)
        n_c = [v for k, v in res.items() if k.startswith(lvl) and v["kind"] == "clean"]
        n_d = [v for k, v in res.items() if k.startswith(lvl) and v["kind"] == "defect"]
        print(f"[{lvl}] clean scans quiet: {sum(v['ok'] for v in n_c)}/{len(n_c)} | defects found: {sum(v['found'] for v in n_d)}/{sum(v['of'] for v in n_d)} "
              f"({sum(v['ok'] for v in n_d)}/{len(n_d)} pairs fully) | defect pairs with serious spurious findings: {sum(bool(v['extra']) for v in n_d)}/{len(n_d)}", flush=True)
    if a.compare:
        old = json.loads(Path(a.compare).read_text(encoding="utf-8"))
        for k, v in res.items():
            o = old.get(k)
            if o and (o["ok"] != v["ok"] or bool(o["extra"]) != bool(v["extra"])):
                print(f"  CHANGED {k}: ok {o['ok']}->{v['ok']}  spurious {o['extra']}->{v['extra']}")
    else:
        Path(ROOT / "results").mkdir(exist_ok=True)
        (ROOT / "results" / "bench_scan.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        for k, v in res.items():
            if not v["ok"] or v["extra"]:
                print(f"  {k}: {'MISSED' if v['kind']=='defect' and not v['ok'] else ''} {v['extra']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
