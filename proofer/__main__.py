"""python -m proofer REFERENCE.pdf SAMPLE.pdf [--deck approved_text.docx] [-o report.html] [--json out.json] [--csv out.csv]

Exit status: 0 = PASS, 1 = FAIL (major/critical differences), 3 = REVIEW (minor differences or something
needs a human eye), 2 = usage / file error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .compare import Config, compare
from .report import build_html, build_payload, findings_csv, page_assets, sha256


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="proofer", description="Compare a sample packaging PDF against the approved reference PDF (either side may be a JPG or PNG instead).")
    ap.add_argument("reference", help="approved artwork: a PDF, or a JPG/PNG of it")
    ap.add_argument("sample", help="sample to check: a PDF, or a JPG/PNG of it")
    ap.add_argument("--deck", help="approved text document (.docx, .txt or .pdf) to check the sample against")
    ap.add_argument("-o", "--html", help="write a self-contained HTML report here")
    ap.add_argument("--json", help="write the full proof (findings, coverage) as JSON here")
    ap.add_argument("--csv", help="write the findings as CSV here")
    ap.add_argument("--pdf", help="write the sample PDF with every finding annotated on it here")
    ap.add_argument("--dpi", type=int, default=Config.dpi, help="render resolution for visual + barcode checks (default 300)")
    ap.add_argument("--no-ocr", action="store_true", help="don't OCR changed regions")
    ap.add_argument("--profile", choices=["standard", "strict", "lenient", "print_run"], help="tolerance profile (default: the app's saved setting)")
    ap.add_argument("--version", action="version", version=f"packaging-proofer {__version__}")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for p in (args.reference, args.sample) + ((args.deck,) if args.deck else ()):
        if not Path(p).is_file():
            print(f"error: not a file: {p}", file=sys.stderr)
            return 2

    from . import profiles
    settings = profiles.load()
    if args.profile:
        settings["profile"] = args.profile
    cfg = profiles.make_config(settings, dpi=args.dpi, ocr=not args.no_ocr)
    res = compare(args.reference, args.sample, cfg, keep_images=bool(args.html or args.json or args.csv or args.pdf), deck=args.deck, settings=settings)
    d = res.to_dict()
    c = d["counts"]
    print(f"{res.verdict}: {c['critical']} critical, {c['major']} major, {c['minor']} minor" + ("  (limited coverage: some checks could not run)" if res.coverage_limited else ""))
    for f in res.findings:
        print(f"  #{f.id:<2} [{f.severity:8}] p{f.page + 1} {f.category}/{f.kind}: {f.message}")
    for a in res.attention:
        print(f"  ! {a['message']}")
    hashes = dict(ref=sha256(args.reference), sample=sha256(args.sample)) | (dict(deck=sha256(args.deck)) if args.deck else {})
    meta = dict(sha256=hashes, config={k: getattr(cfg, k) for k in cfg.__dataclass_fields__})
    ref_name, smp_name = Path(args.reference).name, Path(args.sample).name
    if args.json or args.csv or args.pdf:
        assets = [page_assets(pg) for pg in res.pages]
        payload = build_payload(res, ref_name, smp_name, cfg, assets, lambda i, k: f"page{i}_{k}.png", meta)
        if args.json:
            Path(args.json).write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        if args.csv:
            Path(args.csv).write_text(findings_csv(payload), encoding="utf-8")
        if args.pdf:
            from .annotate import build
            Path(args.pdf).write_bytes(build(args.sample, payload))
            print(f"annotated PDF: {args.pdf}")
    if args.html:
        Path(args.html).write_text(build_html(res, ref_name, smp_name, cfg=cfg, meta=meta, deck_name=Path(args.deck).name if args.deck else ""), encoding="utf-8")
        print(f"report: {args.html}")
    return {"PASS": 0, "FAIL": 1, "REVIEW": 3}[res.verdict]


if __name__ == "__main__":
    sys.exit(main())
