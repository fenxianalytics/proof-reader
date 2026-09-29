"""Build an approved-text document (copy deck) for each sample design, as a stand-in for the client's Word files.

    python make_decks.py        # writes samples/decks/<design>.docx

Paragraphs come from the master artwork, deliberately put in a different order and without the artwork's line
breaks, the way a real copy deck differs from the laid-out pack.
"""
import random
import re
from pathlib import Path

import pymupdf

from proofer.compare import _text_blocks
from proofer.copydeck import write_docx

ROOT = Path(__file__).parent
MASTERS = dict(syrup="master.pdf", carton="master_carton.pdf", vial="master_vial.pdf", tube="master_tube.pdf",
               leaflet="master_leaflet.pdf", blister="master_blister.pdf")


def main():
    out = ROOT / "samples" / "decks"
    out.mkdir(parents=True, exist_ok=True)
    for design, fn in MASTERS.items():
        doc = pymupdf.open(ROOT / "samples" / fn)
        paras = [b["text"] for pg in doc for b in _text_blocks(pg) if not re.fullmatch(r"[\d\s]{8,}", b["text"])]
        seen, uniq = set(), []
        for t in paras:  # repeated text (blister cells) is one line in a copy deck
            if t not in seen:
                seen.add(t); uniq.append(t)
        random.Random(design).shuffle(uniq)
        write_docx(uniq, str(out / f"{design}.docx"))
        print(f"{design:8} {len(uniq):3} paragraphs -> samples/decks/{design}.docx")


if __name__ == "__main__":
    main()
