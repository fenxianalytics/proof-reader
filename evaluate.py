"""Score the proofer against the ground-truth answer key.

    python make_samples.py     # once
    python evaluate.py         # prints a table, writes results/summary.md + results/details.json

For every injected defect we ask three questions:
  detected     - did ANY finding land on the defect's region?
  classified   - was it reported as the right kind of problem (text / barcode / ...)?
  severity ok  - was it rated at least as serious as it should be?
Controls (pairs with nothing wrong) must produce zero findings.
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from proofer import Config, compare

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')  # Windows consoles default to cp1252 and choke on arrows/degree signs
from proofer.compare import SEV_RANK, _inter, _pad

ROOT = Path(__file__).parent
SAMPLES = ROOT / "samples"
RESULTS = ROOT / "results"


def touches(f, region, pad=4.0):
    zone = _pad(region, pad)
    return any(r and _inter(r, zone) > 0 for r in (f.bbox_a, f.bbox_b, *f.detail.get("also_at", [])))


def run(cfg: Config | None = None, verbose=True):
    key = json.loads((SAMPLES / "answer_key.json").read_text(encoding="utf-8"))
    rows, per_pair = [], []
    t0 = time.time()
    for pair in key["pairs"]:
        res = compare(str(SAMPLES / pair["a"]), str(SAMPLES / pair["b"]), cfg, keep_images=False)
        real = [f for f in res.findings if f.severity != "info"]
        claimed = set()
        for d in pair["defects"]:
            if d["region"] is None:
                hits = [f for f in real if f.category == "structure"]
            else:
                hits = [f for f in real if touches(f, d["region"])]
            good = [f for f in hits if f.category in d["expected_categories"]]
            sev_ok = any(SEV_RANK[f.severity] >= SEV_RANK[d["min_severity"]] for f in good)
            claimed.update(id(f) for f in hits)
            rows.append(dict(pair=pair["name"], defect=d["id"], design=pair.get("design", "syrup"), expected=d["expected_categories"], min_sev=d["min_severity"],
                             detected=bool(hits), classified=bool(good), severity_ok=sev_ok,
                             got=[f"{f.category}/{f.kind}/{f.severity}" for f in hits]))
        extra = [f for f in real if id(f) not in claimed]
        per_pair.append(dict(pair=pair["name"], kind=pair["kind"], n_defects=len(pair["defects"]), n_findings=len(real),
                             verdict=res.verdict, attention=[a["message"] for a in res.attention],
                             spurious=[f"{f.category}/{f.kind}: {f.message}" for f in extra], note=pair.get("note", ""),
                             messages=[f"{f.severity} {f.category}/{f.kind}: {f.message}" for f in real]))
    dt = time.time() - t0

    n = len(rows)
    det = sum(r["detected"] for r in rows)
    cls = sum(r["classified"] for r in rows)
    sev = sum(r["severity_ok"] for r in rows)
    controls = [p for p in per_pair if p["kind"] == "control"]
    false_alarm = [p for p in controls if p["n_findings"] > 0]  # findings only: an attention note (e.g. fine print on a resampled copy) is honesty, not an alarm
    missed_verdict = [p for p in per_pair if p["kind"] == "defect" and p["verdict"] == "PASS"]
    spurious = [(p["pair"], s) for p in per_pair if p["kind"] == "defect" for s in p["spurious"]]

    by_cat = defaultdict(lambda: [0, 0])
    for r in rows:
        c = r["expected"][0]
        by_cat[c][1] += 1
        by_cat[c][0] += r["classified"]

    if verbose:
        print(f"\n{'pair':42} {'defect':34} det cls sev  got")
        for r in rows:
            print(f"{r['pair'][:42]:42} {r['defect'][:34]:34} {'Y' if r['detected'] else '-':>3} {'Y' if r['classified'] else '-':>3} {'Y' if r['severity_ok'] else '-':>3}  {', '.join(r['got'])[:70]}")
        print("\nControls (must be silent):")
        for p in controls:
            print(f"  {'FALSE ALARM' if p in false_alarm else 'ok         '}  {p['pair']:40} verdict={p['verdict']} findings={p['n_findings']}  {p['note']}")
            for m in p["attention"]:
                print(f"       ! {m[:120]}")
            for s in p["spurious"]:
                print(f"       - {s[:110]}")
        print(f"\nSpurious findings on defect pairs (not near any injected defect): {len(spurious)}")
        for pn, s in spurious:
            print(f"  [{pn}] {s[:120]}")
    def block(title, rs):
        m = len(rs)
        if not m:
            return
        d, c, s = (sum(r[k] for r in rs) for k in ("detected", "classified", "severity_ok"))
        print(f"{title}  ({m} injected defects)")
        print(f"  detected (any finding on it):       {d}/{m}  = {100 * d / m:.1f}%")
        print(f"  detected AND correctly classified:  {c}/{m}  = {100 * c / m:.1f}%")
        print(f"  ...and rated serious enough:        {s}/{m}  = {100 * s / m:.1f}%")

    live = [r for r in rows if not r["pair"].startswith("imageonly_")]
    img = [r for r in rows if r["pair"].startswith("imageonly_")]
    print("\n" + "=" * 70)
    block("LIVE-TEXT PDFs (normal artwork exports)", live)
    print()
    block("IMAGE-ONLY PDFs (flattened / outlined artwork)", img)
    print()
    print("By design:")
    for design in sorted({r["design"] for r in rows}):
        block(f"  {design}", [r for r in rows if r["design"] == design])
    redundant = [(p["pair"], p["n_findings"] - p["n_defects"], p["messages"]) for p in per_pair
                 if p["kind"] == "defect" and p["n_findings"] > p["n_defects"]]
    n_redundant = sum(r[1] for r in redundant)
    if verbose and redundant:
        print("\nPairs reporting more findings than injected defects (a defect may be described twice, e.g. bars-vs-digits):")
        for pn, extra_n, msgs in redundant:
            print(f"  {pn}: +{extra_n}")
            for m in msgs:
                print(f"      {m[:150]}")
    print(f"\nControl pairs with false alarms:      {len(false_alarm)}/{len(controls)}")
    print(f"Defect pairs whose overall verdict was PASS: {len(missed_verdict)}/{len([p for p in per_pair if p['kind'] == 'defect'])}")
    print(f"Spurious extra findings:              {len(spurious)}")
    print(f"Redundant findings (beyond 1/defect): {n_redundant}")
    print(f"Runtime: {dt:.1f}s for {len(key['pairs'])} pairs")
    print("=" * 70)

    by_design = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        by_design[r["design"]][0] += r["detected"]
        by_design[r["design"]][1] += r["classified"]
        by_design[r["design"]][2] += 1

    summary = dict(defects=n, detected=det, classified=cls, severity_ok=sev, controls=len(controls),
                   false_alarm_controls=len(false_alarm), spurious=len(spurious), by_category={k: v for k, v in by_cat.items()},
                   by_design={k: v for k, v in by_design.items()},
                   live=dict(n=len(live), classified=sum(r["classified"] for r in live), severity_ok=sum(r["severity_ok"] for r in live)),
                   image_only=dict(n=len(img), classified=sum(r["classified"] for r in img)))
    return summary, rows, per_pair, spurious


if __name__ == "__main__":
    RESULTS.mkdir(exist_ok=True)
    summary, rows, per_pair, spurious = run()
    (RESULTS / "details.json").write_text(json.dumps(dict(summary=summary, rows=rows, pairs=per_pair, spurious=spurious), indent=2), encoding="utf-8")
    missed = [r for r in rows if not r["classified"]]
    sys.exit(1 if missed or summary["false_alarm_controls"] else 0)
