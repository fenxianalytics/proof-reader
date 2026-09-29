"""Build a blind test set: pairs with hidden defects (or none), answer key sealed in a separate file.

    python make_blind.py            # from the 6 original sample designs -> blind_test/
    python make_blind.py --new      # from 5 NEW designs the tool was never tuned on -> blind_test_new/

Run each pair through the app yourself, write down what you think is wrong, THEN open ANSWER_KEY.txt.
"""
import random
import re
import shutil
import sys
from pathlib import Path

import pymupdf

from mutate import MUTATORS, flatten

ROOT = Path(__file__).parent
OUT = ROOT / "blind_test"
MASTERS = ["master.pdf", "master_carton.pdf", "master_vial.pdf", "master_tube.pdf", "master_leaflet.pdf", "master_blister.pdf"]
DECKS = {"master.pdf": "syrup", "master_carton.pdf": "carton", "master_vial.pdf": "vial", "master_tube.pdf": "tube",
         "master_leaflet.pdf": "leaflet", "master_blister.pdf": "blister"}


def _new_masters(out: Path) -> tuple[list[Path], dict]:
    """Render the new designs and write an approved-text document for each (paragraphs in a different order)."""
    import newdesigns
    from proofer.compare import _text_blocks
    from proofer.copydeck import write_docx
    d = out / "_masters"
    d.mkdir(parents=True)
    masters, decks = [], {}
    for name in newdesigns.DESIGNS:
        pdf = d / f"{name}.pdf"
        newdesigns.build(name, str(pdf))
        paras, seen = [], set()
        for pg in pymupdf.open(pdf):
            for b in _text_blocks(pg):
                if b["text"] not in seen and not re.fullmatch(r"[\d\s]{8,}", b["text"]):
                    seen.add(b["text"]); paras.append(b["text"])
        random.Random(name).shuffle(paras)
        write_docx(paras, str(d / f"{name}.docx"))
        masters.append(pdf)
        decks[pdf.name] = d / f"{name}.docx"
    return masters, decks


def main(n: int = 12, seed: int | None = None, new: bool = False):
    rng = random.Random(seed)
    out = ROOT / ("blind_test_new" if new else "blind_test")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    global OUT
    OUT = out
    if new:
        masters, new_decks = _new_masters(out)
    plan = ["clean"] * 3 + ["defect"] * (n - 3)
    rng.shuffle(plan)
    key = ["ANSWER KEY - open only after you've run every pair.", ""]
    for i, kind in enumerate(plan, 1):
        if new:
            srcp = rng.choice(masters)
            deck = new_decks[srcp.name]
        else:
            src = rng.choice(MASTERS)
            srcp = ROOT / "samples" / src
            deck = ROOT / "samples" / "decks" / f"{DECKS[src]}.docx"
        tag = f"pair_{i:02d}"
        ref, smp = OUT / f"{tag}_reference.pdf", OUT / f"{tag}_sample.pdf"
        shutil.copy(srcp, ref)
        if deck.exists():
            shutil.copy(deck, OUT / f"{tag}_approved_text.docx")
        doc = pymupdf.open(srcp)
        what = []
        if kind == "defect":
            for _ in range(rng.choice([1, 1, 2])):  # some pairs hide two defects
                for _try in range(20):
                    mut = rng.choice(list(MUTATORS))
                    pno = rng.randrange(len(doc))
                    res = MUTATORS[mut](doc[pno], random.Random(rng.random()))
                    if res:
                        what.append(f"page {pno + 1}: {res[0]}")
                        break
        tmp = OUT / f"_{tag}.pdf"
        doc.save(tmp, garbage=1)
        if rng.random() < 0.25:  # some samples arrive as flattened, image-only artwork
            flatten(str(tmp), str(smp))
            what.append("(sample was sent as flattened image-only artwork)")
        else:
            shutil.copy(tmp, smp)
        tmp.unlink()
        key.append(f"{tag}: " + ("; ".join(w for w in what if not w.startswith("(")) or "NO DEFECT - should pass")
                   + (" " + " ".join(w for w in what if w.startswith("(")) if any(w.startswith("(") for w in what) else ""))
    (OUT / "ANSWER_KEY.txt").write_text("\n".join(key) + "\n", encoding="utf-8")
    print(f"{n} pairs written to {OUT}. Don't open ANSWER_KEY.txt until you've run them.")


if __name__ == "__main__":
    main(new="--new" in sys.argv)
