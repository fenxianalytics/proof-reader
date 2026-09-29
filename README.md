---
title: Fenxi Proofer
emoji: 🔍
colorFrom: purple
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Fenxi Proofer

Artwork proofing for packaging. It compares a **sample** PDF (or a JPG/PNG - a photo of the printed piece
or a flat scan) against the **approved artwork** and, optionally, against the **approved text document**
(the copy deck), then reports every difference with the reason it fired. Everything runs locally; files
never leave the machine.

A JPG or PNG is wrapped into a one-page PDF automatically and runs the same "image-only artwork" path a
flattened, image-only PDF already takes: no text layer to diff word-by-word, so text and copy-deck checks
fall back to visual comparison plus OCR. Barcode, colour, layout and registration checks work the same either
way. For a full text check, use a live-text PDF on at least one side.

```bash
pip install -r requirements.txt
python app.py                       # web app on http://127.0.0.1:8000
python -m proofer ref.pdf sample.pdf --deck approved.docx -o report.html --csv findings.csv --pdf annotated.pdf
python -m proofer.batch FOLDER -o OUT            # a whole folder of pairs
```

CLI exit code: `0` PASS, `1` FAIL, `3` REVIEW, `2` usage error.

## What it checks

Independent checks run on every page and are merged so that one real difference becomes one finding.

| Check | How |
|---|---|
| **Text** | Words read straight from the PDF text layer (no OCR), grouped into paragraphs by geometry, matched, then diffed word by word. Digits and units are critical. |
| **Approved text (copy deck)** | Each paragraph of a Word / text / PDF document is located on the sample wherever it sits (panel order and line breaks don't matter), then diffed word by word. Also reports approved text that is missing and artwork text the document doesn't account for. Repeats of approved text on other panels are recognised. |
| **Spelling** | Seven language dictionaries plus `dictionary.txt` (product names). Only *new* unknown words become findings; words the approved reference already contains are listed in the coverage report. |
| **Barcodes** | Every symbology zxing-cpp reads (EAN, Code128, DataMatrix, QR, ...): value, check digit, rotation, position, size, the printed caption vs the bars, and a print-quality proxy (contrast, reflectance, quiet zone). |
| **Braille** | Dots read from the PDF's vector drawing commands and decoded to letters on both sides (grade 1, English). |
| **Colour** | Fill and stroke colours read from the PDF's paint commands, plus a CIE-Lab comparison of the rendered pages. |
| **Layers** | Optional-content groups (varnish, spot finishes) added, removed or toggled. |
| **Page structure** | Page count and alignment (an inserted page doesn't shift the rest), trim / bleed boxes, rotation, unembedded fonts, image resolution drops. |
| **Visual** | 300 dpi render, clustered changes classified as moved / removed / added / recoloured / restyled. A "move" must realign almost perfectly, so an edited element can't be written off as moved. |
| **Registration** | A sample that is shifted, scaled, rotated or photographed is detected (matched words, or image features plus RANSAC), reported once ("whole page scaled to 98.5%"), and aligned before every other check - so a re-imposed file doesn't bury the one real change under dozens of "moved" findings. Phone photos and skewed scans are straightened and their lighting evened out, and are marked as limited coverage. |
| **Ink separations** | Both pages rendered to CMYK and each plate compared on its own: K-only black rebuilt as rich black, colours rebuilt from different inks. Invisible on screen, different on press. |
| **Spot colours & overprint** | Named spot inks (Pantone and other Separation / DeviceN colours) and overprint flags read from the PDF's own objects: a spot swapped for another, added or dropped, or overprint switched on / off. |
| **Fine print on low-resolution images** | Small numbers in the reference's live text are OCR'd in the sample and in a copy of the reference degraded to scan quality; a change is reported only when the degraded reference still reads correctly, so an OCR misread can't raise an alarm. |
| **Page order** | Pages are paired by content, so swapped, inserted or removed pages are reported once instead of mis-pairing every page after them. |
| **OCR** | On image-only artwork, changed regions and barcode captions are read with a real OCR engine (never a language model), and the approved-text check runs on the OCR text. |

## Profiles and variable data

**Settings** in the app (or `--profile` on the CLI) chooses how strict a proof is: **Standard** (validated defaults), **Strict**
(regulated artwork approval), **Lenient** (screening; minor differences become notes) or **Print run check**, where lot / batch /
expiry / serial fields are *expected* to differ and a change right after one of those labels is reported as variable data
instead of a defect. The labels are editable. Individual tolerances (colour ΔE, position, smallest mark, ink plate, barcode,
dpi) can be overridden; every proof records the settings it ran with.

## Outputs

- The interactive report (side by side, overlay, swipe, flicker; accept / reject; sign-off with a hash-chained audit log).
- **Annotated PDF**: the sample file with every finding as a real PDF comment (opens in Acrobat), plus a summary page.
- Standalone offline HTML, CSV of findings, full JSON; for batches a ZIP of every report and one CSV of all findings.

## Why you can trust a result

- **Three-state verdict.** FAIL = a major or critical difference. REVIEW = only minor differences, or something needs a
  human eye. PASS = nothing found by any check that ran.
- **Coverage is always shown.** Each page lists which checks ran and which couldn't (for example, text on image-only
  artwork). A clean result on limited coverage is labelled as such, never passed off as a full check.
- **Confidence per finding.** `high` means read directly from the file; `medium` means inferred from pixels or OCR.
- **Every finding explains itself**: the measured value and the threshold it crossed.
- **Review and sign-off.** Accept or reject each finding, then approve or send back. Every decision is stored in an
  append-only, hash-chained log with the SHA-256 of every input file. Editing or deleting an entry breaks the chain,
  and the report says so.

## Measuring accuracy

Two independent measurements, both reproducible:

```bash
python make_samples.py && python make_decks.py   # build the sample designs and their approved-text documents
python evaluate.py                               # hand-built answer key: 82 defects + 17 clean controls
python mutate.py                                 # mutation testing: hundreds of defects injected programmatically
python mutate.py real/*.pdf --per 6              # the same on real, approved client artwork
```

`mutate.py` takes any approved PDF, injects known defects (digit changes, swaps, dropped decimal points, unit
changes, typos, deleted words, moved text, removed images, recolours, stray marks), checks each one both as a
live-text file and flattened to pixels, and reports recall per defect type with the exact 95% upper bound on the
miss rate. It also measures the approved-text check on its own. See the **Validation** page in the app for the latest run.

Latest runs (2026-09-26):

| | Result |
|---|---|
| Answer key | **82 / 82** defects detected, correctly classified and rated serious enough (68 live text, 14 image-only); **0 / 17** clean controls flagged; 0 spurious findings |
| Mutation testing (6 designs, 540 injected defects, live + flattened) | **540 / 540** caught; 95% upper bound on the miss rate **0.6%**; **0 / 12** clean controls flagged |
| Approved-text check on its own (text defects, no reference PDF) | 87% live text, 80% image-only (OCR); a second line of defence, not the primary check |

### Read this before quoting numbers

- The sample designs are synthetic and the tool was tuned on them. Mutation testing on *their* approved artwork
  (`real/`) is what supports a claim about their files. Put 10-20 approved PDFs there and run `python mutate.py`.
- Mutation testing measures the defect types it injects. The pilot should also replay their historical errors.
- On image-only artwork that was resampled (for example, a 150 dpi scan), text under 6 pt can be missed by the
  pixel check. The report warns when this applies.
- Colour is vector colorant values plus rendered RGB, not true CMYK / spot separations. Barcode grading is a
  print-quality proxy, not ISO/IEC 15416. Braille is grade 1 English.
- Not validated for regulated (GxP / 21 CFR Part 11) use. The audit trail is tamper-evident, but formal
  validation is a separate piece of work.

## Batch proofing

In the app, **Batch** takes a whole folder: files are paired by name (`x_reference.pdf` + `x_sample.pdf` (+ `x_approved_text.docx`),
or `reference/` and `sample/` folders with matching names, or versions `x_v3.pdf` -> `x_v4.pdf`), you check the pairing, and every
proof runs in turn on a live dashboard sorted worst-first, with a ZIP of all reports and one CSV of every finding. From the command line:

```bash
python -m proofer.batch FOLDER -o OUT --workers 2     # OUT/<pair>.html, summary.csv, findings.csv
```

`PROOFER_WORKERS` sets how many proofs the web app runs at once (default 2).

## Blind tests

```bash
python make_blind.py            # 12 pairs from the original designs, answer key sealed in ANSWER_KEY.txt
python make_blind.py --new      # 12 pairs from 5 designs the tool was never tuned on
python make_hard.py             # 15 hard pairs: multi-defect, near known limits, and out-of-scope cases
```

## Demo pack

```bash
python make_demo.py      # demo/*.html (offline reports) + demo/DEMO_SCRIPT.md (talk track)
```

## Layout

```
app.py                 web app (FastAPI)
proofer/compare.py     comparison engine
proofer/copydeck.py    approved-text check
proofer/spelling.py    spell check
proofer/ocr.py         OCR wrapper (optional dependency)
proofer/jobs.py        proof jobs, review + sign-off, hash-chained audit log
proofer/report.py      report payload, standalone HTML / CSV export
proofer/web/           browser UI (no build step)
evaluate.py            answer-key scoring
mutate.py              mutation testing
make_demo.py           demo pack
```

## Roadmap

1. Tune on the client's own artwork and historical errors (`real/`).
2. Overprint *simulation* (today overprint flags are detected, not rendered) and spot-plate rendering.
3. ISO/IEC 15416 / 15415 barcode grading.
4. Grade 2 and non-English braille.
5. Optional AI second reader on image-only artwork (adds findings, never removes them), off by default.
6. Users and roles, and a formal validation package for regulated use.
