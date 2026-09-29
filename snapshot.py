"""Regression snapshot: record every finding for every test pair, then check later changes against it.

    python snapshot.py --save results/snapshot.json     # before a refactor
    python snapshot.py --check results/snapshot.json    # after: any difference in a finding, verdict or count is reported

Pairs: examples/, samples/ (the answer key set), blind_test*/ . Timing and peak memory are recorded per pair
(memory needs `pip install psutil`; without it only time is recorded). Findings are compared exactly, timing and
memory are reported as ratios and never fail the check.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

from proofer import Config, compare

ROOT = Path(__file__).parent


def pairs():
    out = []
    ex = ROOT / "examples" / "index.json"
    if ex.exists():
        for p in json.loads(ex.read_text(encoding="utf-8"))["pairs"]:
            out.append((p["name"], ROOT / "examples" / p["a"], ROOT / "examples" / p["b"], ROOT / "examples" / p["deck"] if p.get("deck") else None))
    ak = ROOT / "samples" / "answer_key.json"
    if ak.exists():
        for p in json.loads(ak.read_text(encoding="utf-8"))["pairs"]:
            deck = ROOT / "samples" / "decks" / f"{p.get('design', 'syrup')}.docx"
            out.append((f"samples/{p['name']}", ROOT / "samples" / p["a"], ROOT / "samples" / p["b"], deck if deck.exists() else None))
    for d in ("blind_test", "blind_test_new", "blind_test_hard"):
        for ref in sorted((ROOT / d).glob("pair_*_reference.pdf")):
            n = ref.name[:7]
            deck = ref.with_name(f"{n}_approved_text.docx")
            out.append((f"{d}/{n}", ref, ref.with_name(f"{n}_sample.pdf"), deck if deck.exists() else None))
    return out


class Peak:
    def __init__(self):
        try:
            import psutil
            self.p = psutil.Process()
        except ImportError:
            self.p = None
        self.peak, self._stop = 0.0, threading.Event()

    def __enter__(self):
        if self.p:
            self.peak = self.p.memory_info().rss
            threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self):
        while not self._stop.is_set():
            self.peak = max(self.peak, self.p.memory_info().rss)
            time.sleep(0.02)

    def __exit__(self, *a):
        self._stop.set()


def record(ref, smp, deck):
    with Peak() as pk:
        t = time.time()
        r = compare(str(ref), str(smp), Config(), keep_images=False, deck=str(deck) if deck else None)
        dt = time.time() - t
    fs = sorted([f.severity, f.category, f.kind, f.page, f.message, [round(v, 1) for v in (f.bbox_a or [])], [round(v, 1) for v in (f.bbox_b or [])]]
                for f in r.findings)
    return dict(verdict=r.verdict, counts=r.to_dict()["counts"], findings=fs, secs=round(dt, 2), mb=round(pk.peak / 2**20) if pk.p else None)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--save")
    g.add_argument("--check")
    a = ap.parse_args()
    ps = pairs()
    base = json.loads(Path(a.check).read_text(encoding="utf-8")) if a.check else {}
    snap, bad, t_old, t_new = {}, 0, 0.0, 0.0
    for i, (name, ref, smp, deck) in enumerate(ps, 1):
        rec = record(ref, smp, deck)
        snap[name] = rec
        if a.check:
            old = base.get(name)
            if old is None:
                print(f"NEW      {name}")
                continue
            t_old, t_new = t_old + old["secs"], t_new + rec["secs"]
            if old["findings"] != rec["findings"] or old["verdict"] != rec["verdict"]:
                bad += 1
                so, sn = {json.dumps(f) for f in old["findings"]}, {json.dumps(f) for f in rec["findings"]}
                print(f"DIFFERS  {name}: {len(so - sn)} findings gone, {len(sn - so)} new")
                for f in list(so - sn)[:3]: print("   - " + f[:170])
                for f in list(sn - so)[:3]: print("   + " + f[:170])
        print(f"[{i}/{len(ps)}] {name}  {rec['verdict']}  {len(rec['findings'])} findings  {rec['secs']}s  {rec['mb']} MB", flush=True)
    if a.save:
        Path(a.save).parent.mkdir(parents=True, exist_ok=True)
        Path(a.save).write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        print(f"saved {len(snap)} pairs -> {a.save}")
    else:
        print(f"\n{len(ps) - bad}/{len(ps)} identical; {bad} differ. Time {t_new:.0f}s vs {t_old:.0f}s before.")
        mbs = [(r["mb"] or 0) for r in snap.values()]
        mbo = [(base[n]["mb"] or 0) for n in snap if n in base]
        if mbs and mbo:
            print(f"Peak memory (max over pairs): {max(mbs)} MB vs {max(mbo)} MB before.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
