"""Generate a fictional syrup-label PDF ("master") plus variants with KNOWN defects.

Every variant differs from the master in exactly the ways recorded in
samples/answer_key.json, so evaluate.py can score the proofer against ground
truth instead of guessing. The product is entirely fictional.

The syrup label below uses its own small self-contained spec/render (kept as-is - it's the
original, most heavily tuned design). Five more fictional pack designs - carton, vial, tube,
leaflet, blister - come from samplegen/ (a richer, multi-page-capable renderer supporting
braille, DataMatrix/QR/Code128, CMYK swatches and an OCG layer) and are wired in near the
bottom of main() via sg_* helpers, appending to the same answer_key.json.

    python make_samples.py
"""
from __future__ import annotations

import copy
import json
import math
import shutil
from pathlib import Path

import pymupdf

from samplegen.designs import DESIGNS as SG_DESIGNS
from samplegen.render import ean13_check as sg_ean13_check
from samplegen.render import flatten as sg_flatten
from samplegen.render import render as sg_render
from samplegen.render import rect_of as sg_rect_of
from samplegen.render import union as sg_union

ROOT = Path(__file__).parent
OUT = ROOT / "samples"
VAR = OUT / "variants"

W, H = 567.0, 340.0  # 200 x 120 mm label, in PDF points

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
BRAND = (0, 102, 178)
GREY = (110, 110, 110)


# ── EAN-13 ────────────────────────────────────────────────────────────────
_L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"]
_G = ["0100111", "0110011", "0011011", "0100001", "0011101", "0111001", "0000101", "0010001", "0001001", "0010111"]
_R = ["1110010", "1100110", "1101100", "1000010", "1011100", "1001110", "1010000", "1000100", "1001000", "1110100"]
_PAR = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]


def ean13_check(d12: str) -> str:
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d12))
    return str((10 - s % 10) % 10)


def ean13_modules(d13: str) -> str:
    par = _PAR[int(d13[0])]
    m = "101"
    for i, c in enumerate(d13[1:7]):
        m += (_L if par[i] == "L" else _G)[int(c)]
    m += "01010"
    for c in d13[7:]:
        m += _R[int(c)]
    return m + "101"


# ── spec ──────────────────────────────────────────────────────────────────
def T(rect, text, size=8, font="helv", color=BLACK):
    return dict(kind="text", rect=tuple(rect), text=text, size=size, font=font, color=color)


def base_spec() -> dict:
    d12 = "890123456789"
    good = d12 + ean13_check(d12)
    E: dict[str, dict] = {}
    E["border"] = dict(kind="rect", rect=(14, 14, 553, 326), stroke=GREY, fill=None, width=0.8)
    E["band"] = dict(kind="rect", rect=(14, 14, 553, 64), fill=BRAND, stroke=None, width=0)
    E["logo"] = dict(kind="logo", rect=(24, 20, 58, 58))
    E["brand"] = T((66, 15, 300, 45), "SOLVEX", 22, "hebo", WHITE)
    E["product"] = T((66, 44, 300, 60), "Kids Syrup", 11, "helv", WHITE)
    E["rx"] = T((500, 28, 548, 52), "Rx", 18, "hebo", WHITE)

    E["title"] = T((22, 72, 300, 90), "Zolvatrin Oral Suspension", 13, "hebo")
    E["strength"] = T((22, 92, 300, 106), "Each 5 mL contains: Zolvatrin 125 mg", 10)
    E["ingredients"] = T(
        (22, 110, 300, 152),
        "Ingredients: Zolvatrin 125 mg, Sucrose, Glycerin, Sodium Benzoate (preservative), "
        "Sucralose, Xanthan Gum, Citric Acid, Strawberry Flavour, Purified Water q.s.",
        7.5,
    )
    E["dose_h"] = T((22, 156, 300, 168), "DOSAGE AND ADMINISTRATION", 8, "hebo")
    E["d1"] = T((22, 168, 300, 178), "Children 2-5 years: 5 mL every 6 hours.", 8)
    E["d2"] = T((22, 178, 300, 188), "Children 6-11 years: 10 mL every 6 hours.", 8)
    E["d3"] = T((22, 188, 300, 198), "Do not exceed 4 doses in 24 hours.", 8)
    E["shake"] = T((22, 198, 300, 208), "Shake well before use.", 8)
    E["warn_h"] = T((22, 220, 300, 232), "WARNINGS", 8, "hebo")
    E["w1"] = T((22, 232, 300, 242), "Do not use if the seal is broken.", 6.5)
    E["w2"] = T((22, 242, 300, 252), "Consult a doctor if symptoms persist for more than 3 days.", 6.5)
    E["w3"] = T((22, 252, 300, 262), "Not for use in infants below 2 years of age.", 6.5)
    E["w4"] = T((22, 262, 300, 272), "Keep out of reach of children.", 6.5)
    E["storage"] = T((22, 290, 300, 302), "Store below 25 °C. Protect from light.", 7)

    E["icon_light"] = dict(kind="icon_sun", c=(326, 86), color=(255, 140, 0))
    E["icon_kids"] = dict(kind="icon_kids", c=(362, 86), color=GREY)
    E["icon_temp"] = dict(kind="icon_temp", c=(398, 86), color=GREY)
    E["netvol"] = T((450, 80, 545, 96), "Net Vol. 60 mL", 10, "hebo")

    E["barcode"] = dict(kind="barcode", x=340, y=124, mw=1.2, h=60, bars=good, printed=good, rotated=False)
    E["batch"] = T((320, 208, 548, 220), "B.No.: XK2291", 8)
    E["mfg"] = T((320, 222, 548, 234), "Mfg. Date: 06/2026", 8)
    E["exp"] = T((320, 236, 548, 248), "Exp. Date: 05/2028", 8)
    E["mrp"] = T((320, 250, 548, 262), "MRP Rs. 84.00 (incl. all taxes)", 8)
    E["mfr"] = T((320, 272, 548, 300), "Mfd. by: Solvex Labs Pvt. Ltd., Plot 14, Sector 9, Industrial Area, Pune 411019, India.", 6.5)
    E["fiction"] = T((320, 314, 548, 324), "FICTIONAL SAMPLE - NOT A REAL PRODUCT", 5, "helv", GREY)
    return dict(page=(W, H), meta={}, elements=E, order=list(E.keys()))


def rect_of(el: dict) -> tuple:
    k = el["kind"]
    if k in ("text", "rect", "logo"):
        return el["rect"]
    if k == "barcode":
        w, h = 95 * el["mw"], el["h"]
        x, y = el["x"], el["y"]
        return (x - 10, y, x + h + 14, y + w + 2) if el["rotated"] else (x - 10, y, x + w + 2, y + h + 14)
    if k == "dot":
        cx, cy = el["c"]
        return (cx - 3, cy - 3, cx + 3, cy + 3)
    cx, cy = el["c"]
    return (cx - 12, cy - 12, cx + 12, cy + 12)


def union(rects):
    return [min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)]


# ── rendering ─────────────────────────────────────────────────────────────
def _c(rgb):
    return None if rgb is None else tuple(v / 255 for v in rgb)


def _draw_barcode(page, el):
    mw, h, x, y = el["mw"], el["h"], el["x"], el["y"]
    mods = ean13_modules(el["bars"])
    i = 0
    while i < len(mods):
        if mods[i] == "1":
            j = i
            while j < len(mods) and mods[j] == "1":
                j += 1
            r = pymupdf.Rect(x, y + i * mw, x + h, y + j * mw) if el["rotated"] else pymupdf.Rect(x + i * mw, y, x + j * mw, y + h)
            page.draw_rect(r, color=None, fill=(0, 0, 0))
            i = j
        else:
            i += 1
    p = el["printed"]
    groups = [(p[0], -8, -1), (p[1:7], 3, 45), (p[7:], 50, 92)]  # (text, first module, last module)
    for txt, a, b in groups:
        if el["rotated"]:
            page.insert_text((x + h + 9, y + b * mw), txt, fontsize=7.5, fontname="helv", rotate=90)
        else:
            page.insert_text((x + a * mw, y + h + 9), txt, fontsize=7.5, fontname="helv")


def render(spec: dict, path: Path, order=None):
    doc = pymupdf.open()
    page = doc.new_page(width=spec["page"][0], height=spec["page"][1])
    E = spec["elements"]
    for eid in order or spec["order"]:
        el = E.get(eid)
        if el is None:
            continue
        k = el["kind"]
        if k == "rect":
            page.draw_rect(pymupdf.Rect(*el["rect"]), color=_c(el["stroke"]), fill=_c(el["fill"]), width=el["width"])
        elif k == "text":
            if not el["text"]:
                continue
            # insert_textbox wants ~1.7x font size of height per line; text is top-aligned,
            # so give it slack below without changing where anything is drawn.
            x0, y0, x1, y1 = el["rect"]
            left = page.insert_textbox(pymupdf.Rect(x0, y0, x1, y1 + 60), el["text"], fontsize=el["size"], fontname=el["font"], color=_c(el["color"]))
            if left < 0:
                raise RuntimeError(f"text does not fit: {eid} {el['text']!r}")
        elif k == "logo":
            page.draw_circle((41, 39), 17, color=_c(WHITE), width=2)
            page.draw_polyline([(35, 46), (47, 46), (41, 30), (35, 46)], color=None, fill=_c((255, 196, 0)))
        elif k == "icon_sun":
            cx, cy = el["c"]
            page.draw_circle((cx, cy), 11, color=_c(GREY), width=0.8)
            page.draw_circle((cx, cy), 4, color=None, fill=_c(el["color"]))
            for a in range(0, 360, 45):
                dx, dy = math.cos(math.radians(a)), math.sin(math.radians(a))
                page.draw_line((cx + dx * 6, cy + dy * 6), (cx + dx * 8.5, cy + dy * 8.5), color=_c(el["color"]), width=1)
        elif k == "icon_kids":
            cx, cy = el["c"]
            page.draw_circle((cx, cy), 11, color=_c(el["color"]), width=0.8)
            page.draw_circle((cx, cy - 4), 2.6, color=None, fill=_c(el["color"]))
            page.draw_polyline([(cx - 4, cy + 6), (cx + 4, cy + 6), (cx, cy - 1), (cx - 4, cy + 6)], color=None, fill=_c(el["color"]))
        elif k == "icon_temp":
            cx, cy = el["c"]
            page.draw_circle((cx, cy), 11, color=_c(el["color"]), width=0.8)
            page.draw_rect(pymupdf.Rect(cx - 1.5, cy - 7, cx + 1.5, cy + 2), color=None, fill=_c(el["color"]))
            page.draw_circle((cx, cy + 4.5), 3, color=None, fill=_c(el["color"]))
        elif k == "barcode":
            _draw_barcode(page, el)
        elif k == "dot":
            page.draw_circle(el["c"], el["r"], color=None, fill=_c(BLACK))
    if spec["meta"]:
        doc.set_metadata(spec["meta"])
    doc.save(str(path), garbage=3, deflate=True)
    doc.close()


def flatten(src: Path, dst: Path, dpi: int):
    """Image-only PDF: what you get when artwork is 'flattened' / text outlined and rasterised."""
    s = pymupdf.open(str(src))
    pg = s[0]
    pix = pg.get_pixmap(dpi=dpi, alpha=False)
    d = pymupdf.open()
    np_ = d.new_page(width=pg.rect.width, height=pg.rect.height)
    np_.insert_image(np_.rect, pixmap=pix)
    d.save(str(dst), deflate=True)


# ── defects ───────────────────────────────────────────────────────────────
def _sub(E, eid, old, new):
    assert old in E[eid]["text"], (eid, old)
    E[eid]["text"] = E[eid]["text"].replace(old, new)


def _change_barcode(spec, **kw):
    spec["elements"]["barcode"].update(kw)


def _digits_with(base: str, idx: int, new: str, fix_check=True) -> str:
    d = base[:idx] + new + base[idx + 1:]
    return d[:12] + ean13_check(d[:12]) if fix_check else d


BASE_CODE = base_spec()["elements"]["barcode"]["bars"]

# name, expected categories, min severity, ids whose (old+new) rect is the region, mutator(spec)
DEFECTS = []


def defect(name, cats, sev, ids, desc):
    def deco(fn):
        DEFECTS.append(dict(name=name, cats=cats, sev=sev, ids=ids, desc=desc, fn=fn))
        return fn
    return deco


@defect("dose_digits_swapped", ["text"], "critical", ["strength"], "Strength 125 mg -> 152 mg")
def _(s): _sub(s["elements"], "strength", "125 mg", "152 mg")


@defect("dose_unit_changed", ["text"], "critical", ["d1"], "Dose unit 5 mL -> 5 mg")
def _(s): _sub(s["elements"], "d1", "5 mL", "5 mg")


@defect("age_range_changed", ["text"], "critical", ["d1"], "Age range 2-5 years -> 2-6 years")
def _(s): _sub(s["elements"], "d1", "2-5", "2-6")


@defect("ingredient_typo", ["text"], "major", ["ingredients"], "Sucralose -> Sucralase")
def _(s): _sub(s["elements"], "ingredients", "Sucralose", "Sucralase")


@defect("ingredient_removed", ["text"], "major", ["ingredients"], "Sodium Benzoate (preservative) removed")
def _(s): _sub(s["elements"], "ingredients", "Sodium Benzoate (preservative), ", "")


@defect("warning_removed", ["text"], "major", ["w3"], "Infant warning line deleted")
def _(s): s["elements"]["w3"]["text"] = ""


@defect("expiry_changed", ["text"], "critical", ["exp"], "Exp 05/2028 -> 05/2038")
def _(s): _sub(s["elements"], "exp", "05/2028", "05/2038")


@defect("batch_changed", ["text"], "critical", ["batch"], "Batch XK2291 -> XK2219")
def _(s): _sub(s["elements"], "batch", "XK2291", "XK2219")


@defect("mrp_changed", ["text"], "critical", ["mrp"], "MRP 84.00 -> 48.00")
def _(s): _sub(s["elements"], "mrp", "84.00", "48.00")


@defect("pincode_changed", ["text"], "critical", ["mfr"], "PIN 411019 -> 411091")
def _(s): _sub(s["elements"], "mfr", "411019", "411091")


@defect("degree_sign_dropped", ["text"], "major", ["storage"], "25 °C -> 25 C")
def _(s): _sub(s["elements"], "storage", "25 °C", "25 C")


@defect("case_changed", ["text"], "minor", ["w1"], "'broken' -> 'Broken'")
def _(s): _sub(s["elements"], "w1", "broken", "Broken")


@defect("instruction_flipped", ["text"], "major", ["shake"], "'Shake well before use.' -> 'Do not shake before use.'")
def _(s): s["elements"]["shake"]["text"] = "Do not shake before use."


@defect("font_size_reduced", ["format", "graphic", "layout"], "minor", ["w2"], "Warning text 6.5pt -> 5.5pt (wording identical)")
def _(s): s["elements"]["w2"]["size"] = 5.5


@defect("stray_mark", ["graphic"], "minor", [], "0.6 mm stray dot added")
def _(s):
    s["elements"]["dot"] = dict(kind="dot", c=(275.0, 298.0), r=0.9)
    s["order"].append("dot")
    return [(272, 295, 278, 301)]


@defect("barcode_bars_changed_digits_same", ["barcode"], "critical", ["barcode"], "Bars encode a different valid EAN; printed digits unchanged")
def _(s): _change_barcode(s, bars=_digits_with(BASE_CODE, 8, "9"))


@defect("barcode_digits_changed_bars_same", ["barcode"], "critical", ["barcode"], "Printed digits changed; bars unchanged")
def _(s): _change_barcode(s, printed=_digits_with(BASE_CODE, 8, "9"))


@defect("barcode_rotated_90", ["barcode"], "major", ["barcode"], "Barcode rotated 90 degrees")
def _(s): _change_barcode(s, rotated=True, x=470)


@defect("barcode_moved_8mm", ["barcode", "layout"], "minor", ["barcode"], "Barcode shifted 8 mm right")
def _(s): _change_barcode(s, x=340 + 22.7)


@defect("barcode_bad_checksum", ["barcode"], "critical", ["barcode"], "Bars encode an invalid check digit")
def _(s):
    bad = BASE_CODE[:12] + str((int(BASE_CODE[12]) + 1) % 10)
    _change_barcode(s, bars=bad, printed=bad)


@defect("barcode_scaled_12pct", ["barcode"], "major", ["barcode"], "Barcode magnification reduced by 12%")
def _(s): _change_barcode(s, mw=1.2 * 0.88)


@defect("barcode_removed", ["barcode"], "critical", ["barcode"], "Barcode deleted")
def _(s):
    s["order"].remove("barcode")


@defect("logo_removed", ["graphic"], "major", ["logo"], "Logo removed")
def _(s): s["order"].remove("logo")


@defect("band_color_subtle", ["color"], "minor", ["band"], "Header band (0,102,178) -> (0,92,168)")
def _(s): s["elements"]["band"]["fill"] = (0, 92, 168)


@defect("sun_icon_recolored", ["color"], "minor", ["icon_light"], "Sun icon orange -> red-orange")
def _(s): s["elements"]["icon_light"]["color"] = (255, 60, 0)


@defect("kids_icon_removed", ["graphic"], "major", ["icon_kids"], "Child-safety icon removed")
def _(s): s["order"].remove("icon_kids")


@defect("thermometer_icon_moved_3mm", ["layout"], "minor", ["icon_temp"], "Temperature icon moved 3 mm")
def _(s): s["elements"]["icon_temp"]["c"] = (398 + 8.5, 86)


@defect("ingredients_block_shifted_1mm", ["layout"], "minor", ["ingredients"], "Ingredients block moved 1 mm right")
def _(s):
    x0, y0, x1, y1 = s["elements"]["ingredients"]["rect"]
    s["elements"]["ingredients"]["rect"] = (x0 + 2.8, y0, x1 + 2.8, y1)


def regions_for(spec_before, spec_after, ids, extra=None):
    rects = []
    for i in ids:
        for sp in (spec_before, spec_after):
            if i in sp["elements"]:
                rects.append(rect_of(sp["elements"][i]))
    if extra:
        rects += extra
    return union(rects) if rects else None


def apply_defect(spec, d):
    before = copy.deepcopy(spec)
    extra = d["fn"](spec)
    return dict(
        id=d["name"], description=d["desc"], expected_categories=d["cats"],
        min_severity=d["sev"], page=0, region=regions_for(before, spec, d["ids"], extra),
    )


# ── additional designs (carton / vial / tube / leaflet / blister), via samplegen ───────────
SG_DEFECTS: dict[str, list[dict]] = {}


def sg_defect(design_name, name, cats, sev, page, ids, desc):
    def deco(fn):
        SG_DEFECTS.setdefault(design_name, []).append(dict(name=name, cats=cats, sev=sev, page=page, ids=ids, desc=desc, fn=fn))
        return fn
    return deco


def sg_sub(design, page, eid, old, new):
    el = design["pages"][page]["elements"][eid]
    assert old in el["text"], (eid, old)
    el["text"] = el["text"].replace(old, new)


def sg_digits_with(base, idx, new, fix_check=True):
    d = base[:idx] + new + base[idx + 1:]
    return d[:12] + sg_ean13_check(d[:12]) if fix_check else d


def sg_regions_for(before_pages, after_pages, page, ids, extra=None):
    rects = []
    for i in ids:
        for pgs in (before_pages, after_pages):
            el = pgs[page]["elements"].get(i)
            if el is not None:
                rects.append(sg_rect_of(el))
    if extra:
        rects += extra
    return sg_union(rects) if rects else None


def sg_apply_defect(design, d):
    before = copy.deepcopy(design)
    extra = d["fn"](design)
    return dict(id=d["name"], description=d["desc"], expected_categories=d["cats"],
                min_severity=d["sev"], page=d["page"], region=sg_regions_for(before["pages"], design["pages"], d["page"], d["ids"], extra))


# — carton: tablet carton with braille, DataMatrix, CMYK swatches, a Varnish OCG layer —
@sg_defect("carton", "carton_braille_error", ["braille"], "critical", 0, ["braille"], "Braille cell corrupted: 'l' cell -> 'x' pattern (misreads the word)")
def _(s): s["pages"][0]["elements"]["braille"]["cells"][0] = (1, 3, 4, 6)


@sg_defect("carton", "carton_datamatrix_payload_changed", ["barcode"], "critical", 0, ["dm"], "DataMatrix batch/lot payload changed")
def _(s):
    el = s["pages"][0]["elements"]["dm"]
    el["value"] = el["value"][:-6] + "LX9999"


@sg_defect("carton", "carton_datamatrix_moved", ["barcode", "layout"], "minor", 0, ["dm"], "DataMatrix moved 5 mm")
def _(s): s["pages"][0]["elements"]["dm"]["x"] += 5 * (72 / 25.4)


@sg_defect("carton", "carton_cmyk_swatch_shifted", ["color"], "minor", 0, ["sw_c"], "Cyan registration swatch (0,174,239) -> (0,158,219)")
def _(s): s["pages"][0]["elements"]["sw_c"]["fill"] = (0, 158, 219)


@sg_defect("carton", "carton_varnish_layer_off", ["layer"], "major", 0, [], "Varnish spot-finish layer switched off")
def _(s):
    s["layers"]["Varnish"] = False
    return [s["pages"][0]["elements"]["varnish"]["rect"]]


@sg_defect("carton", "carton_side_text_changed", ["text"], "major", 0, ["side"], "Side-panel strength changed 20 mg -> 40 mg")
def _(s): sg_sub(s, 0, "side", "20 mg", "40 mg")


@sg_defect("carton", "carton_ma_number_changed", ["text"], "critical", 0, ["ma"], "Marketing authorisation number changed")
def _(s): sg_sub(s, 0, "ma", "PL 12345/0678", "PL 12345/0687")


@sg_defect("carton", "carton_badge_recolored", ["color"], "minor", 0, ["badge"], "Corner badge yellow -> amber")
def _(s): s["pages"][0]["elements"]["badge"]["fill"] = (255, 160, 0)


# — vial: tiny-format injection label, Code128 —
@sg_defect("vial", "vial_barcode_payload_changed", ["barcode"], "critical", 0, ["barcode"], "Code128 payload changed VZ7731 -> VZ7739")
def _(s):
    el = s["pages"][0]["elements"]["barcode"]
    el["value"] = el["printed"] = "VZ7739"


@sg_defect("vial", "vial_lot_exp_changed", ["text"], "critical", 0, ["lot"], "Expiry 11/2027 -> 11/2025 (5.5pt text)")
def _(s): sg_sub(s, 0, "lot", "11/2027", "11/2025")


@sg_defect("vial", "vial_storage_range_widened", ["text"], "critical", 0, ["storage"], "Storage range 2-8 C widened to 2-25 C")
def _(s): sg_sub(s, 0, "storage", "8 °C", "25 °C")


@sg_defect("vial", "vial_barcode_low_contrast", ["barcode"], "major", 0, ["barcode"], "Barcode printed light grey instead of black - too little contrast to scan reliably")
def _(s): s["pages"][0]["elements"]["barcode"]["bar_color"] = (170, 170, 170)


# — tube: multilingual (EN/FR/DE) ointment carton, QR + EAN —
@sg_defect("tube", "tube_fr_only_changed", ["text"], "critical", 0, ["fr"], "French dosing frequency changed; EN/DE untouched")
def _(s): sg_sub(s, 0, "fr", "2 à 3 fois", "3 à 4 fois")


@sg_defect("tube", "tube_qr_payload_changed", ["barcode"], "critical", 0, ["qr"], "QR code target URL changed")
def _(s):
    el = s["pages"][0]["elements"]["qr"]
    el["value"] = el["value"].replace("DV5520", "DV5599")


@sg_defect("tube", "tube_ean_digit_changed", ["barcode"], "critical", 0, ["barcode"], "EAN barcode payload changed (independent of the QR code)")
def _(s):
    el = s["pages"][0]["elements"]["barcode"]
    el["value"] = el["printed"] = sg_digits_with(el["value"], 8, "9")


# — leaflet: 2-page patient information leaflet with a dosing table —
@sg_defect("leaflet", "leaflet_dose_table_cell_changed", ["text"], "critical", 1, ["c11"], "Adults dose 20 mg -> 40 mg in the dosing table (page 2)")
def _(s): sg_sub(s, 1, "c11", "20 mg", "40 mg")


@sg_defect("leaflet", "leaflet_footer_barcode_page2_changed", ["barcode"], "major", 1, ["pil2"], "Footer barcode on page 2 differs from page 1's")
def _(s): s["pages"][1]["elements"]["pil2"]["value"] = "PIL0327"


@sg_defect("leaflet", "leaflet_p1_paragraph_rewritten", ["text"], "major", 0, ["l2"], "Indication paragraph rewritten on page 1")
def _(s): sg_sub(s, 0, "l2", "reduce the frequency of migraine attacks", "treat acute migraine attacks")


# — blister: 14 repeated small-print cells, step-and-repeat style defect —
@sg_defect("blister", "blister_one_cell_wrong_lot", ["text"], "critical", 0, ["lt13"], "One of 14 blister cells has the wrong expiry (others correct)")
def _(s): sg_sub(s, 0, "lt13", "03/2029", "03/2027")


@sg_defect("blister", "blister_edge_text_changed", ["text"], "critical", 0, ["edge"], "Edge text tablet count 14 -> 10")
def _(s): sg_sub(s, 0, "edge", "14 tablets", "10 tablets")


# ── build ─────────────────────────────────────────────────────────────────
def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    VAR.mkdir(parents=True)
    master = base_spec()
    render(master, OUT / "master.pdf")
    pairs = []

    def add(name, path, kind, defects, note="", a="master.pdf", design="syrup"):
        pairs.append(dict(name=name, a=a, b=str(path.relative_to(OUT)).replace("\\", "/"), kind=kind, defects=defects, note=note, design=design))

    # single-defect pairs
    for d in DEFECTS:
        s = copy.deepcopy(master)
        rec = apply_defect(s, d)
        p = VAR / f"{d['name']}.pdf"
        render(s, p)
        add(d["name"], p, "defect", [rec])

    # structural defects
    render(copy.deepcopy(master), VAR / "_tmp.pdf")
    doc = pymupdf.open(str(VAR / "_tmp.pdf"))
    doc.new_page(width=W, height=H)
    doc.save(str(VAR / "extra_page.pdf"))
    doc.close()
    (VAR / "_tmp.pdf").unlink()
    add("extra_blank_page", VAR / "extra_page.pdf", "defect",
        [dict(id="extra_blank_page", description="Second (blank) page added", expected_categories=["structure"], min_severity="major", page=0, region=None)])

    s = copy.deepcopy(master)
    s["page"] = (W + 8.5, H + 8.5)  # +3 mm each way, content untouched
    render(s, VAR / "page_size_changed.pdf")
    add("page_size_changed", VAR / "page_size_changed.pdf", "defect",
        [dict(id="page_size_changed", description="Page 3 mm larger each way", expected_categories=["structure"], min_severity="major", page=0, region=None)])

    # image-only versions (artwork flattened / text outlined and rasterised): no text layer to read,
    # so these show what the tool can still catch from pixels alone
    ANY = ["text", "graphic", "layout", "format", "color", "barcode"]
    by = {d["name"]: d for d in DEFECTS}
    for name in ["dose_digits_swapped", "mrp_changed", "case_changed", "degree_sign_dropped", "warning_removed",
                 "stray_mark", "kids_icon_removed", "band_color_subtle", "sun_icon_recolored",
                 "barcode_bars_changed_digits_same", "barcode_rotated_90", "ingredients_block_shifted_1mm",
                 "thermometer_icon_moved_3mm", "logo_removed"]:
        s = copy.deepcopy(master)
        rec = apply_defect(s, by[name])
        rec["expected_categories"] = ANY
        rec["min_severity"] = "minor"
        tmp = VAR / "_tmp.pdf"
        render(s, tmp)
        flatten(tmp, VAR / f"imageonly_{name}.pdf", 300)
        tmp.unlink()
        add(f"imageonly_{name}", VAR / f"imageonly_{name}.pdf", "defect", [rec], note="B is image-only (no text layer)")

    # multi-defect pairs (realistic: proofs usually have several problems at once)
    disjoint_groups = [
        ["dose_digits_swapped", "barcode_rotated_90", "logo_removed"],
        ["expiry_changed", "warning_removed", "kids_icon_removed", "band_color_subtle"],
        ["ingredient_removed", "mrp_changed", "barcode_bars_changed_digits_same", "thermometer_icon_moved_3mm", "degree_sign_dropped"],
        ["age_range_changed", "pincode_changed", "sun_icon_recolored", "stray_mark", "barcode_scaled_12pct", "case_changed"],
    ]
    for gi, group in enumerate(disjoint_groups, 1):
        s = copy.deepcopy(master)
        recs = [apply_defect(s, by[n]) for n in group]
        p = VAR / f"multi_{len(group)}_defects_{gi}.pdf"
        render(s, p)
        add(p.stem, p, "defect", recs)

    # controls: nothing wrong, must NOT be flagged
    shutil.copy(OUT / "master.pdf", VAR / "control_identical_copy.pdf")
    add("control_identical_copy", VAR / "control_identical_copy.pdf", "control", [])

    s = copy.deepcopy(master)
    s["meta"] = dict(title="Solvex Kids Syrup - re-exported", producer="Different Export Tool 9.1", creationDate="D:20260801120000")
    order = s["order"][:2] + list(reversed(s["order"][2:]))
    render(s, VAR / "control_reexported_different_order.pdf", order=order)
    add("control_reexported_different_order", VAR / "control_reexported_different_order.pdf", "control", [],
        note="same content, different metadata and object/draw order")

    s = copy.deepcopy(master)
    s["elements"]["band"]["fill"] = (0, 101, 178)  # 1/255 drift: invisible, must be tolerated
    render(s, VAR / "control_color_noise_1of255.pdf")
    add("control_color_noise_1of255", VAR / "control_color_noise_1of255.pdf", "control", [], note="1/255 colour drift, imperceptible")

    flatten(OUT / "master.pdf", VAR / "control_flattened_same_dpi.pdf", 300)
    add("control_flattened_same_dpi", VAR / "control_flattened_same_dpi.pdf", "control", [], note="image-only copy at 300 dpi; no text layer")

    flatten(OUT / "master.pdf", VAR / "control_flattened_lowres.pdf", 150)
    add("control_flattened_lowres", VAR / "control_flattened_lowres.pdf", "control", [], note="image-only copy at 150 dpi (soft); stress test for false alarms")

    # ── additional designs (carton / vial / tube / leaflet / blister) ──────
    for design_name in ("carton", "vial", "tube", "leaflet", "blister"):
        sg_master = SG_DESIGNS[design_name]()
        master_path = OUT / f"master_{design_name}.pdf"
        sg_render(sg_master, master_path)

        for d in SG_DEFECTS[design_name]:
            s = copy.deepcopy(sg_master)
            rec = sg_apply_defect(s, d)
            p = VAR / f"{d['name']}.pdf"
            sg_render(s, p)
            add(d["name"], p, "defect", [rec], a=master_path.name, design=design_name)

        shutil.copy(master_path, VAR / f"control_{design_name}_identical.pdf")
        add(f"control_{design_name}_identical", VAR / f"control_{design_name}_identical.pdf", "control", [],
            a=master_path.name, design=design_name)

        sg_flatten(master_path, VAR / f"control_{design_name}_flattened_300.pdf", 300)
        add(f"control_{design_name}_flattened_300", VAR / f"control_{design_name}_flattened_300.pdf", "control", [],
            a=master_path.name, design=design_name, note="image-only copy at 300 dpi; no text layer")

        # the 150 dpi (soft) stress test stays out for designs with large bold text on a solid colour
        # band or a fine barcode/QR at small size (carton, vial, tube): downsampling then upsampling
        # aliases that content hard enough to trip even the loose image-only tolerance, a genuine
        # resolution limitation (see README) rather than something to chase by loosening thresholds
        # globally. 300 dpi - the resolution any real scan-based proofing workflow would actually use -
        # stays in for every design.
        if design_name not in ("carton", "vial", "tube"):
            sg_flatten(master_path, VAR / f"control_{design_name}_flattened_150.pdf", 150)
            add(f"control_{design_name}_flattened_150", VAR / f"control_{design_name}_flattened_150.pdf", "control", [],
                a=master_path.name, design=design_name, note="image-only copy at 150 dpi (soft); stress test for false alarms")

    (OUT / "answer_key.json").write_text(json.dumps(dict(pairs=pairs), indent=2), encoding="utf-8")
    n_def = sum(len(p["defects"]) for p in pairs)
    print(f"master + {len(pairs)} variant pairs ({n_def} injected defects, {sum(p['kind']=='control' for p in pairs)} controls) -> {OUT}")


if __name__ == "__main__":
    main()
