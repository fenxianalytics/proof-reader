"""Five NEW fictional pack designs, drawn with their own code (not samplegen/), for blind testing on artwork
the proofer was never tuned on. Different fonts (Times, Courier), rotated dieline panels, ruled tables, raster
barcodes, photo-like images, Spanish / Italian / French / German text, 4 pt fine print.
All names, codes and numbers are invented. Nothing here is a real product.
"""
from __future__ import annotations

import numpy as np
import pymupdf
import zxingcpp

MM = 72 / 25.4
BLACK, WHITE, GREY = (0, 0, 0), (1, 1, 1), (0.45, 0.45, 0.45)


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def text(pg, rect, s, size, font="helv", color=BLACK, align=0, rotate=0):
    r = pymupdf.Rect(rect)
    rc = pg.insert_textbox(r, s, fontsize=size, fontname=font, color=color, align=align, rotate=rotate)
    if rc < 0:  # didn't fit: grow the box downwards (or sideways when rotated) so nothing is silently dropped
        grow = -rc + size
        r2 = pymupdf.Rect(r.x0, r.y0, r.x1 + (grow if rotate else 0), r.y1 + (0 if rotate else grow))
        pg.insert_textbox(r2, s, fontsize=size, fontname=font, color=color, align=align, rotate=rotate)


def box(pg, rect, fill=None, stroke=None, width=0.8, radius=None):
    pg.draw_rect(pymupdf.Rect(rect), color=stroke, fill=fill, width=width, radius=radius)


def raster_code(pg, x, y, value, fmt, scale=2, rotate=0, height_pt=None, hri=None, hri_size=7):
    b = zxingcpp.create_barcode(value, getattr(zxingcpp.BarcodeFormat, fmt))
    im = np.array(b.to_image(scale=scale))
    h, w = im.shape
    pix = pymupdf.Pixmap(pymupdf.csGRAY, w, h, np.ascontiguousarray(im).tobytes(), False)
    pw, ph = w * 72 / 300 * 1.0, (height_pt or h * 72 / 300)
    if rotate:
        r = pymupdf.Rect(x, y, x + ph, y + pw)
    else:
        r = pymupdf.Rect(x, y, x + pw, y + ph)
    pg.insert_image(r, pixmap=pix, rotate=rotate, keep_proportion=False)
    if hri:
        text(pg, (r.x0, r.y1 + 1, r.x1 + 20, r.y1 + hri_size + 4), hri, hri_size, "cour", align=0)
    return r


def photo(pg, rect, seed, c1, c2):
    rng = np.random.default_rng(seed)
    w, h = 360, 240
    yy, xx = np.mgrid[0:h, 0:w] / np.array([h, w])[:, None, None]
    t = (0.6 * xx + 0.4 * yy)[..., None]
    img = (np.array(c1) * (1 - t) + np.array(c2) * t) * 255
    for _ in range(9):
        cx, cy, rad = rng.random() * w, rng.random() * h, 15 + rng.random() * 45
        m = ((np.arange(w)[None, :] - cx) ** 2 + (np.arange(h)[:, None] - cy) ** 2) < rad ** 2
        img[m] = img[m] * 0.6 + rng.random(3) * 255 * 0.4
    img = np.clip(img, 0, 255).astype(np.uint8)
    pix = pymupdf.Pixmap(pymupdf.csRGB, w, h, img.tobytes(), False)
    pg.insert_image(pymupdf.Rect(rect), pixmap=pix)


def ean13(d12: str) -> str:
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d12))
    return d12 + str((10 - s % 10) % 10)


# ── 1. eye-drop carton, flat dieline with four panels (ES / IT) ───────────
def eyedrops(doc):
    pg = doc.new_page(width=170 * MM, height=110 * MM)
    teal = _rgb("#0e7c86")
    W = pg.rect.width
    panels = [0, 40 * MM, 85 * MM, 125 * MM, W]
    for x in panels[1:-1]:
        pg.draw_line((x, 6), (x, pg.rect.height - 6), color=(0.8, 0.2, 0.6), width=0.4, dashes="[3 2] 0")
    # panel A (side, rotated): lot / expiry
    text(pg, (6, 10, 30, 300), "Lote: OC-5518   Cad.: 11/2027", 7, "cobo", rotate=90)
    text(pg, (30, 10, 110, 290), "Conservar por debajo de 25 °C. Desechar 28 días después de abrir.", 6, "helv", rotate=90)
    # panel B (front)
    x0 = panels[1]
    box(pg, (x0 + 4, 8, panels[2] - 4, 60), fill=teal)
    text(pg, (x0 + 10, 14, panels[2] - 8, 40), "OCUVERA", 20, "hebo", WHITE)
    text(pg, (x0 + 10, 40, panels[2] - 8, 58), "colirio en solución", 9, "helv", WHITE)
    text(pg, (x0 + 10, 70, panels[2] - 8, 100), "Nepralast 0,5 mg/mL", 11, "hebo")
    text(pg, (x0 + 10, 100, panels[2] - 8, 120), "1 frasco de 5 mL", 9)
    photo(pg, (x0 + 10, 130, panels[2] - 10, 200), 3, (0.1, 0.5, 0.55), (0.85, 0.95, 0.95))
    box(pg, (x0 + 10, 215, panels[2] - 10, 240), stroke=teal, width=1.2, radius=0.2)
    text(pg, (x0 + 12, 222, panels[2] - 12, 238), "SIN CONSERVANTES", 7, "hebo", teal, align=1)
    # panel C (back, Italian)
    x0 = panels[2]
    text(pg, (x0 + 6, 10, panels[3] - 4, 24), "Composizione", 8, "hebo")
    text(pg, (x0 + 6, 24, panels[3] - 4, 90), "1 mL di soluzione contiene 0,5 mg di nepralast. Eccipienti: sodio cloruro, "
                                              "sodio fosfato bibasico, acqua per preparazioni iniettabili.", 6.5)
    text(pg, (x0 + 6, 94, panels[3] - 4, 108), "Posologia", 8, "hebo")
    text(pg, (x0 + 6, 108, panels[3] - 4, 170), "Adulti: 1 goccia nell'occhio interessato 2 volte al giorno. "
                                               "Non superare 4 gocce al giorno.", 6.5)
    text(pg, (x0 + 6, 175, panels[3] - 4, 230), "Tenere fuori dalla vista e dalla portata dei bambini. Solo per uso oftalmico.", 6)
    # panel D (side): barcode + DataMatrix
    x0 = panels[3]
    raster_code(pg, x0 + 8, 20, ean13("840612345678")[:-1], "EAN13", scale=2, height_pt=40, hri=ean13("840612345678"))
    raster_code(pg, x0 + 10, 100, "0108406123456783172711301OC5518", "DataMatrix", scale=6)
    text(pg, (x0 + 6, 170, W - 4, 200), "Titular: Ocuvera Farma S.L., Valencia", 5.5)
    text(pg, (x0 + 6, 290, W - 4, 305), "MUESTRA FICTICIA", 4.5, "helv", GREY)


# ── 2. vitamin bottle label with a ruled supplement-facts table ───────────
def vitamins(doc):
    pg = doc.new_page(width=180 * MM, height=70 * MM)
    orange = _rgb("#e8731a")
    box(pg, (0, 0, 62 * MM, pg.rect.height), fill=orange)
    text(pg, (10, 18, 62 * MM - 6, 60), "VITAFORT", 22, "tibo", WHITE)
    text(pg, (10, 52, 62 * MM - 6, 80), "Daily Multivitamin", 11, "tiit", WHITE)
    text(pg, (10, 110, 62 * MM - 6, 140), "60 tablets", 12, "tibo", WHITE)
    # supplement facts
    x, y, w = 66 * MM, 8, 64 * MM
    box(pg, (x, y, x + w, 188), stroke=BLACK, width=1)
    text(pg, (x + 4, y + 2, x + w, y + 20), "Supplement Facts", 11, "hebo")
    text(pg, (x + 4, y + 20, x + w, y + 30), "Serving size: 1 tablet", 6.5)
    rows = [("Vitamin C", "80 mg", "100%"), ("Vitamin D3", "25 µg", "125%"), ("Vitamin E", "12 mg", "80%"),
            ("Vitamin B12", "2.5 µg", "100%"), ("Folic Acid", "200 µg", "50%"), ("Zinc", "10 mg", "91%"),
            ("Iron", "7 mg", "39%"), ("Iodine", "150 µg", "100%")]
    yy = y + 34
    pg.draw_line((x, yy - 2), (x + w, yy - 2), width=2)
    text(pg, (x + 4, yy, x + 90, yy + 10), "Ingredient", 6, "hebo")
    text(pg, (x + 92, yy, x + 140, yy + 10), "Amount", 6, "hebo")
    text(pg, (x + 142, yy, x + w - 4, yy + 10), "%NRV", 6, "hebo", align=2)
    yy += 11
    for name, amt, pct in rows:
        pg.draw_line((x, yy - 1), (x + w, yy - 1), width=0.4)
        text(pg, (x + 4, yy, x + 90, yy + 10), name, 6.5)
        text(pg, (x + 92, yy, x + 140, yy + 10), amt, 6.5)
        text(pg, (x + 142, yy, x + w - 4, yy + 10), pct, 6.5, align=2)
        yy += 12
    text(pg, (x + 4, yy + 2, x + w - 4, yy + 20), "NRV = Nutrient Reference Value", 5)
    # right: directions, warnings, QR
    x = 134 * MM
    text(pg, (x, 10, pg.rect.width - 8, 22), "Directions", 7.5, "hebo")
    text(pg, (x, 22, pg.rect.width - 8, 60), "Adults: take one tablet daily with food. Do not exceed the stated daily dose.", 6.5)
    text(pg, (x, 62, pg.rect.width - 8, 110), "Food supplements should not be used as a substitute for a varied diet. "
                                             "Keep out of the reach of young children.", 5.5, "tiro")
    raster_code(pg, x, 118, "https://vitafort.example/lot/VF2291", "QRCode", scale=3)
    text(pg, (x + 50, 122, pg.rect.width - 6, 170), "Lot VF2291\nBest before 03/2028", 6.5, "cour")
    text(pg, (x, 178, pg.rect.width - 6, 190), "Fictional sample", 4, "helv", GREY)


# ── 3. nasal spray pouch, two pages (front / back), Courier small print ───
def nasal(doc):
    red = _rgb("#c62828")
    pg = doc.new_page(width=100 * MM, height=130 * MM)
    box(pg, (6, 6, pg.rect.width - 6, pg.rect.height - 6), stroke=GREY, width=0.6, radius=0.05)
    text(pg, (16, 20, pg.rect.width - 16, 50), "NasoClear", 24, "hebo", _rgb("#1565c0"), align=1)
    text(pg, (16, 52, pg.rect.width - 16, 70), "xylofrine hydrochloride 0.1% w/v", 9, "helv", align=1)
    text(pg, (16, 70, pg.rect.width - 16, 86), "Nasal spray, solution  |  15 mL", 8, "helv", align=1)
    photo(pg, (40, 96, pg.rect.width - 40, 190), 11, (0.8, 0.9, 1.0), (0.2, 0.45, 0.8))
    box(pg, (22, 210, pg.rect.width - 22, 262), stroke=red, width=1.4)
    text(pg, (28, 214, pg.rect.width - 28, 260), "Do not use for more than 7 days. Not for children under 12 years.", 8, "hebo", red, align=1)
    text(pg, (16, 330, pg.rect.width - 16, 350), "FICTIONAL SAMPLE", 4.5, "helv", GREY, align=1)
    pg = doc.new_page(width=100 * MM, height=130 * MM)
    text(pg, (14, 14, pg.rect.width - 14, 28), "HOW TO USE", 8, "cobo")
    steps = ["1. Remove the cap. Prime the pump 3 times before first use.",
             "2. Insert the nozzle into one nostril and spray once.",
             "3. Repeat in the other nostril. Use up to 3 times a day.",
             "4. Wipe the nozzle and replace the cap after use."]
    y = 30
    for s in steps:
        text(pg, (14, y, pg.rect.width - 14, y + 22), s, 6.5, "cour")
        y += 22
    text(pg, (14, y + 6, pg.rect.width - 14, y + 18), "INGREDIENTS", 8, "cobo")
    text(pg, (14, y + 20, pg.rect.width - 14, y + 60), "Each spray (0.14 mL) delivers 140 µg xylofrine hydrochloride. "
                                                       "Also contains: benzalkonium chloride 0.1 mg/mL, sodium chloride, purified water.", 6.5, "cour")
    text(pg, (14, y + 70, pg.rect.width - 14, y + 110), "Store at 15-25 °C. Discard 28 days after opening.", 6.5, "cour")
    raster_code(pg, 14, 280, "NCX-0457-15", "Code128", scale=2, height_pt=30, hri="NCX-0457-15")
    text(pg, (150, 285, pg.rect.width - 10, 320), "PL 99001/0457\nBatch NX7702\nEXP 02/2028", 6, "cour")


# ── 4. insulin pen label: long thin strip, 4 pt fine print ────────────────
def insulin(doc):
    pg = doc.new_page(width=120 * MM, height=24 * MM)
    purple = _rgb("#6a1b9a")
    box(pg, (0, 0, 22 * MM, pg.rect.height), fill=purple)
    text(pg, (4, 10, 22 * MM - 2, 34), "U-100", 13, "hebo", WHITE, align=1)
    text(pg, (4, 36, 22 * MM - 2, 60), "GLUCOPEN", 8, "hebo", WHITE, align=1)
    x = 24 * MM
    text(pg, (x, 5, 90 * MM, 20), "insulin glarevane 100 units/mL", 9, "hebo")
    text(pg, (x, 19, 90 * MM, 30), "Solution for injection in a pre-filled pen, 3 mL (300 units)", 5.5)
    text(pg, (x, 30, 90 * MM, 60), "For subcutaneous use only. Do not mix with other insulins. Use a new needle for each "
                                   "injection. Store unused pens at 2-8 °C; in use, below 30 °C for up to 28 days.", 4)
    text(pg, (90 * MM, 6, pg.rect.width - 4, 40), "Lot GP8830\nEXP 09/2027", 5.5, "cobo")
    raster_code(pg, 90 * MM, 32, "GP-8830-300", "Code128", scale=2, height_pt=22)
    text(pg, (x, 60, 90 * MM, 67), "Fictional sample - not a real product", 3.5, "helv", GREY)


# ── 5. cream box front + back (FR / DE), roundels and a varnish-free zone ──
def cream(doc):
    green = _rgb("#2e7d32")
    pg = doc.new_page(width=95 * MM, height=120 * MM)
    photo(pg, (0, 0, pg.rect.width, 150), 21, (0.95, 0.9, 0.8), (0.55, 0.75, 0.55))
    box(pg, (8, 12, pg.rect.width - 8, 70), fill=WHITE)
    text(pg, (14, 18, pg.rect.width - 14, 50), "Dermacalm", 24, "tibo", green)
    text(pg, (14, 50, pg.rect.width - 14, 66), "crème apaisante  |  beruhigende Creme", 8, "tiit")
    pg.draw_circle((pg.rect.width - 40, 200), 26, color=None, fill=green)
    text(pg, (pg.rect.width - 66, 188, pg.rect.width - 14, 214), "1 %", 16, "hebo", WHITE, align=1)
    text(pg, (14, 170, pg.rect.width - 80, 200), "hydrocortalène", 11, "hebo")
    text(pg, (14, 200, pg.rect.width - 80, 230), "Tube de 30 g / Tube mit 30 g", 8)
    text(pg, (14, 300, pg.rect.width - 14, 320), "Échantillon fictif / Fiktives Muster", 4.5, "helv", GREY)
    pg = doc.new_page(width=95 * MM, height=120 * MM)
    text(pg, (12, 12, pg.rect.width - 12, 24), "FRANÇAIS", 7.5, "hebo", green)
    text(pg, (12, 24, pg.rect.width - 12, 80), "Appliquer une fine couche sur la zone concernée 1 à 2 fois par jour pendant "
                                               "7 jours maximum. Ne pas appliquer sur le visage des enfants de moins de 10 ans.", 6.5)
    text(pg, (12, 88, pg.rect.width - 12, 100), "DEUTSCH", 7.5, "hebo", green)
    text(pg, (12, 100, pg.rect.width - 12, 156), "1-2 mal täglich dünn auf die betroffene Stelle auftragen, höchstens 7 Tage lang. "
                                                "Nicht im Gesicht von Kindern unter 10 Jahren anwenden.", 6.5)
    text(pg, (12, 164, pg.rect.width - 12, 200), "Composition / Zusammensetzung: hydrocortalène 10 mg/g; "
                                                 "excipients / Hilfsstoffe: paraffine, glycérol, eau purifiée.", 5.5)
    box(pg, (12, 215, 110, 265), fill=WHITE, stroke=GREY, width=0.5)
    text(pg, (16, 220, 108, 262), "Lot DC4410\nEXP 06/2028", 7, "cobo")
    raster_code(pg, 130, 215, ean13("376001234567")[:-1], "EAN13", scale=2, height_pt=36, hri=ean13("376001234567"))


DESIGNS = dict(eyedrops=eyedrops, vitamins=vitamins, nasal=nasal, insulin=insulin, cream=cream)


def build(name: str, path: str) -> None:
    doc = pymupdf.open()
    DESIGNS[name](doc)
    doc.save(path, garbage=3, deflate=True)
