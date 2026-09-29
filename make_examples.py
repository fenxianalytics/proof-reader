"""Collect the showcase, extreme and language pairs into examples/ - the built-in examples the web app offers.

    python make_showcase.py && python make_showcase_extreme.py && python make_language_tests.py --build   # once
    python make_examples.py

examples/ is committed to git (unlike demo/ and samples/), so a hosted copy of the app has examples too. PDFs are
re-saved with lossless compression (flattened pages are raw pixels otherwise) to keep the repo small.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).parent
OUT = ROOT / "examples"
SETS = [
    ("Showcase: several errors at once", "showcase", ROOT / "demo" / "showcase"),
    ("Extreme: stress tests and limits", "extreme", ROOT / "demo" / "showcase_extreme"),
]


def _save_small(src: Path, dst: Path):
    d = pymupdf.open(src)
    try:
        d.subset_fonts()          # a full CJK font is ~19 MB; only the used glyphs are needed
    except Exception:
        pass
    d.save(dst, garbage=4, deflate=True, clean=True)
    d.close()


def _scorecard_notes(folder: Path) -> dict[str, str]:
    notes = {}
    sc = folder / "SCORECARD.md"
    if sc.exists():
        for line in sc.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\| \[([^\]]+)\]\([^)]*\) \|(.*)\|\s*$", line)
            if m:
                notes[m.group(1)] = m.group(2).split("|")[-1].strip()
    return notes


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    index = []

    for group, tag, folder in SETS:
        if not folder.exists():
            print(f"skip {folder} (not built)")
            continue
        notes = _scorecard_notes(folder)
        for d in sorted(p for p in folder.iterdir() if p.is_dir()):
            dst = OUT / tag / d.name
            dst.mkdir(parents=True)
            _save_small(d / "reference.pdf", dst / "reference.pdf")
            _save_small(d / "sample.pdf", dst / "sample.pdf")
            deck = d / "approved_text.docx"
            if deck.exists():
                shutil.copy(deck, dst / "approved_text.docx")
            key = d / "INJECTED_DEFECTS.txt"
            n = sum(1 for l in key.read_text(encoding="utf-8").splitlines() if l[:5] in ("FOUND", "MISSE")) if key.exists() else 0
            desc = notes.get(d.name) or (key.read_text(encoding="utf-8").splitlines()[0] if key.exists() else d.name)
            control = "control" in d.name or "clean" in d.name
            index.append(dict(name=f"{tag}/{d.name}", design=group, kind="control" if control else "defect",
                              note="", defects=[dict(description=desc)] if not control else [],
                              base="examples", a=f"{tag}/{d.name}/reference.pdf", b=f"{tag}/{d.name}/sample.pdf",
                              deck=f"{tag}/{d.name}/approved_text.docx" if deck.exists() else ""))

    lt = ROOT / "language_tests"
    if lt.exists():
        key = json.loads((lt / "answer_key.json").read_text(encoding="utf-8"))
        for k in key:
            src, dst = lt / k["name"], OUT / "languages" / k["name"]
            dst.mkdir(parents=True)
            _save_small(src / "reference.pdf", dst / "reference.pdf")
            _save_small(src / "sample.pdf", dst / "sample.pdf")
            control = k["expect"] == "pass"
            index.append(dict(name=f"languages/{k['name']}", design="Languages: Russian, Greek, Chinese, Arabic and more",
                              kind="control" if control else "defect", note="", defects=[dict(description=k["note"])] if not control else [],
                              base="examples", a=f"languages/{k['name']}/reference.pdf", b=f"languages/{k['name']}/sample.pdf", deck=""))

    (OUT / "index.json").write_text(json.dumps(dict(pairs=index), indent=1, ensure_ascii=False), encoding="utf-8")
    mb = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    biggest = max((f for f in OUT.rglob("*.pdf")), key=lambda f: f.stat().st_size)
    print(f"{len(index)} examples, {mb:.0f} MB total; largest file {biggest.stat().st_size / 1e6:.1f} MB ({biggest.relative_to(OUT)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
