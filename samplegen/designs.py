"""Six fictional pack designs. Names, ingredients and codes are invented; nothing here is a real product."""
from __future__ import annotations

from collections import OrderedDict

from .render import BLACK, GREY, WHITE, braille_cells, ean13_check, refit


def T(id_, x0, y0, x1, text, size=8, font="arial", color=BLACK, align=0):
    el = dict(id=id_, kind="text", rect=(x0, y0, x1, y0 + 1), text=text, size=size, font=font, color=color, align=align, auto=True)
    refit(el)
    return el


def TR(id_, rect, text, size, font="arial", color=BLACK, rotate=270):
    return dict(id=id_, kind="text", rect=rect, text=text, size=size, font=font, color=color, rotate=rotate, auto=False)


def R(id_, rect, fill=None, stroke=None, width=0.8, layer=None):
    el = dict(id=id_, kind="rect", rect=rect, fill=fill, stroke=stroke, width=width)
    if layer:
        el["layer"] = layer
    return el


def page(size, els, trimbox=None):
    E = OrderedDict((e["id"], e) for e in els)
    assert len(E) == len(els), "duplicate element id"
    return dict(size=size, elements=E, order=list(E), trimbox=trimbox)


def design(name, pages, layers=None):
    return dict(name=name, pages=pages, layers=layers or {}, meta={})


def ean(gtin12: str) -> str:
    return gtin12 + ean13_check(gtin12)


# ── 1. syrup bottle label, 200 x 120 mm ───────────────────────────────────
def syrup():
    code = ean("890123456789")
    els = [
        R("border", (14, 14, 553, 326), stroke=GREY),
        R("band", (14, 14, 553, 64), fill=(0, 102, 178), width=0),
        dict(id="logo", kind="logo", rect=(24, 20, 58, 58)),
        T("brand", 66, 15, 300, "SOLVEX", 22, "arialbd", WHITE),
        T("product", 66, 44, 300, "Kids Syrup", 11, "arial", WHITE),
        T("rx", 500, 28, 548, "Rx", 18, "arialbd", WHITE),
        T("title", 22, 72, 300, "Zolvatrin Oral Suspension", 13, "arialbd"),
        T("strength", 22, 92, 300, "Each 5 mL contains: Zolvatrin 125 mg", 10),
        T("ingredients", 22, 110, 300, "Ingredients: Zolvatrin 125 mg, Sucrose, Glycerin, Sodium Benzoate (preservative), "
                                        "Sucralose, Xanthan Gum, Citric Acid, Strawberry Flavour, Purified Water q.s.", 7.5),
        T("dose_h", 22, 156, 300, "DOSAGE AND ADMINISTRATION", 8, "arialbd"),
        T("d1", 22, 168, 300, "Children 2-5 years: 5 mL every 6 hours.", 8),
        T("d2", 22, 178, 300, "Children 6-11 years: 10 mL every 6 hours.", 8),
        T("d3", 22, 188, 300, "Do not exceed 4 doses in 24 hours.", 8),
        T("shake", 22, 198, 300, "Shake well before use.", 8),
        T("warn_h", 22, 220, 300, "WARNINGS", 8, "arialbd"),
        T("w1", 22, 232, 300, "Do not use if the seal is broken.", 6.5),
        T("w2", 22, 242, 300, "Consult a doctor if symptoms persist for more than 3 days.", 6.5),
        T("w3", 22, 252, 300, "Not for use in infants below 2 years of age.", 6.5),
        T("w4", 22, 262, 300, "Keep out of reach of children.", 6.5),
        T("storage", 22, 290, 300, "Store below 25 °C. Protect from light.", 7),
        dict(id="icon_light", kind="icon_sun", c=(326, 86), color=(255, 140, 0)),
        dict(id="icon_kids", kind="icon_kids", c=(362, 86), color=GREY),
        dict(id="icon_temp", kind="icon_temp", c=(398, 86), color=GREY),
        T("netvol", 450, 80, 545, "Net Vol. 60 mL", 10, "arialbd"),
        dict(id="barcode", kind="barcode", fmt="ean13", value=code, printed=code, x=340, y=124, mw=1.2, h=60),
        T("batch", 320, 208, 548, "B.No.: XK2291", 8),
        T("mfg", 320, 222, 548, "Mfg. Date: 06/2026", 8),
        T("exp", 320, 236, 548, "Exp. Date: 05/2028", 8),
        T("mrp", 320, 250, 548, "MRP Rs. 84.00 (incl. all taxes)", 8),
        T("mfr", 320, 272, 548, "Mfd. by: Solvex Labs Pvt. Ltd., Plot 14, Sector 9, Industrial Area, Pune 411019, India.", 6.5),
        T("fiction", 320, 314, 548, "FICTIONAL SAMPLE - NOT A REAL PRODUCT", 5, "arial", GREY),
    ]
    return design("syrup", [page((567, 340), els)])


# ── 2. tablet carton front, 90 x 140 mm ───────────────────────────────────
def carton():
    dm = "01" + "0" + ean("890123456780")[:13] + "17" + "290331" + "10" + "LX4471"
    els = [
        R("border", (8, 8, 247, 389), stroke=GREY),
        R("band", (8, 8, 247, 78), fill=(0, 121, 107), width=0),
        T("brand", 20, 18, 180, "LUMEXA", 24, "arialbd", WHITE),
        T("sub", 20, 50, 240, "20 mg film-coated tablets", 9, "arial", WHITE),
        T("rx", 196, 22, 240, "Rx only", 8, "arialbd", WHITE),
        dict(id="illus", kind="image", rect=(20, 88, 112, 158), seed=3, ppi=300),
        R("varnish", (18, 86, 114, 160), stroke=(191, 144, 0), width=1.4, layer="Varnish"),
        dict(id="badge", kind="circle", c=(185, 123), r=36, fill=(255, 193, 7), stroke=None),
        T("strength", 150, 114, 220, "20 mg", 16, "arialbd", BLACK, align=1),
        T("comp", 20, 170, 235, "Each film-coated tablet contains 20 mg Lumexatib (as hydrochloride). Contains lactose. See leaflet for further information.", 7),
        T("dir", 20, 194, 235, "Oral use. Swallow whole with water. Read the package leaflet before use.", 7),
        T("pack", 20, 218, 235, "Pack of 28 tablets", 8.5, "arialbd"),
        T("storage", 20, 234, 235, "Do not store above 30 °C. Store in the original package to protect from moisture.", 7),
        T("kids", 20, 256, 235, "Keep out of the sight and reach of children.", 7),
        TR("side", (236, 86, 246, 300), "LUMEXA 20 mg film-coated tablets - 28 tablets", 6, "arialbd", rotate=270),
        dict(id="braille", kind="braille", text="lumexa", cells=braille_cells("lumexa"), x=22, y=278, r=1.0, pitch=6.0, cell_pitch=17.0),
        dict(id="dm", kind="barcode", fmt="datamatrix", value=dm, printed=None, x=150, y=270, mw=2.4, h=0),
        T("batch", 20, 300, 140, "Batch: LX4471", 7.5),
        T("exp", 20, 312, 140, "Exp: 03/2029", 7.5),
        T("mfg", 20, 324, 140, "Mfg: 04/2026", 7.5),
        T("mrp", 20, 336, 140, "MRP Rs. 312.00", 7.5),
        T("mfr", 150, 334, 245, "Manufactured by: Nordhaven Pharma GmbH, 12 Hafenstrasse, 20457 Hamburg, Germany", 5.5),
        R("sw_c", (20, 372, 30, 381), fill=(0, 174, 239), width=0),
        R("sw_m", (34, 372, 44, 381), fill=(236, 0, 140), width=0),
        R("sw_y", (48, 372, 58, 381), fill=(255, 242, 0), width=0),
        R("sw_k", (62, 372, 72, 381), fill=(35, 31, 32), width=0),
        T("ma", 80, 373, 240, "MA No.: PL 12345/0678", 6.5),
    ]
    return design("carton", [page((255, 397), els, trimbox=(8, 8, 247, 389))], layers={"Varnish": True})


# ── 3. injection vial label, 60 x 39 mm (tiny text) ───────────────────────
def vial():
    els = [
        R("border", (3, 3, 167, 107), stroke=GREY, width=0.6),
        R("band", (3, 3, 167, 22), fill=(198, 40, 40), width=0),
        T("iv", 8, 8, 164, "FOR INTRAVENOUS USE ONLY", 6.5, "arialbd", WHITE),
        T("name", 8, 26, 125, "zolvaTRIN Injection", 11, "arialbd"),
        T("rxonly", 130, 28, 165, "Rx only", 6),
        T("strength", 8, 42, 90, "50 mg/mL", 9, "arialbd"),
        T("vol", 90, 44, 165, "2 mL single-dose vial", 6),
        T("warn", 8, 60, 88, "Discard unused portion. Do not use if particulate matter is present.", 5),
        T("storage", 8, 80, 88, "Store at 2 °C to 8 °C. Do not freeze.", 5),
        dict(id="barcode", kind="barcode", fmt="code128", value="VZ7731", printed="VZ7731", ps=5, x=95, y=62, mw=0.62, h=22),
        T("lot", 8, 94, 165, "Lot: VZ7731   Exp: 11/2027", 5.5),
    ]
    return design("vial", [page((170, 110), els)])


# ── 4. ointment tube carton, multilingual, 150 x 60 mm ────────────────────
def tube():
    code = ean("890765432101")
    els = [
        R("border", (4, 4, 421, 166), stroke=GREY),
        R("band", (4, 4, 140, 166), fill=(123, 31, 162), width=0),
        T("brand", 14, 14, 134, "DERMAVIA", 16, "arialbd", WHITE),
        T("prod", 14, 36, 134, "Calmexol 1 % w/w Ointment", 8.5, "arial", WHITE),
        T("net", 14, 60, 134, "30 g", 13, "arialbd", (255, 214, 0)),
        dict(id="illus", kind="image", rect=(14, 84, 130, 154), seed=8, ppi=300),
        T("en_h", 150, 12, 320, "Ointment for external use", 9, "arialbd"),
        T("en", 150, 25, 320, "Apply a thin layer to the affected area 2 to 3 times daily. Do not swallow. Avoid contact with eyes.", 7),
        T("fr_h", 150, 58, 320, "Pommade à usage externe", 9, "arialbd"),
        T("fr", 150, 71, 320, "Appliquer une fine couche sur la zone concernée 2 à 3 fois par jour. Ne pas avaler. Éviter le contact avec les yeux.", 7),
        T("de_h", 150, 104, 320, "Salbe zur äußerlichen Anwendung", 9, "arialbd"),
        T("de", 150, 117, 320, "Dünn auf die betroffene Stelle auftragen, 2 bis 3 Mal täglich. Nicht verschlucken. Kontakt mit den Augen vermeiden.", 7),
        T("lot", 150, 148, 320, "Lot / Lot / Ch.-B.: DV5520   EXP: 08/2028", 6.5),
        dict(id="qr", kind="barcode", fmt="qr", value="https://dermavia.example/l/DV5520", printed=None, x=345, y=14, mw=1.5, h=0),
        dict(id="icon_kids", kind="icon_kids", c=(346, 80), color=GREY),
        dict(id="icon_light", kind="icon_sun", c=(382, 80), color=(255, 140, 0)),
        dict(id="barcode", kind="barcode", fmt="ean13", value=code, printed=code, x=328, y=100, mw=0.9, h=34),
    ]
    return design("tube", [page((425, 170), els)])


# ── 5. patient leaflet, 2 pages, 148 x 210 mm ─────────────────────────────
def _stack(prefix, x0, x1, y, items):
    els = []
    for i, (kind, text) in enumerate(items):
        e = T(f"{prefix}{i + 1}", x0, y, x1, text, 8 if kind == "h" else 6.8, "arialbd" if kind == "h" else "arial")
        els.append(e)
        y = e["rect"][3] + (3 if kind == "h" else 8)
    return els


def leaflet():
    L, Rr = (30, 200), (220, 390)
    foot = lambda n: [T(f"foot{n}", 30, 562, 300, f"Lumexa PIL v3.2 - Revised 03/2026 - Page {n} of 2", 6.5, "arial", GREY),
                      dict(id=f"pil{n}", kind="barcode", fmt="code128", value="PIL0326", printed=None, x=330, y=554, mw=0.75, h=14)]
    p1 = [
        T("title", 30, 24, 390, "Package leaflet: Information for the patient", 14, "arialbd"),
        T("sub", 30, 46, 390, "Lumexa 20 mg film-coated tablets (lumexatib)", 9, "arialbd"),
        T("read", 30, 62, 390, "Read all of this leaflet carefully before you start taking this medicine because it contains important information for you.", 7.5),
        R("rule", (30, 90, 390, 91), fill=(0, 121, 107), width=0),
    ]
    p1 += _stack("l", *L, 100, [
        ("h", "1. What Lumexa is and what it is used for"),
        ("p", "Lumexa contains the active substance lumexatib. It belongs to a group of medicines called kinase modulators. Lumexa is used in adults to reduce the frequency of migraine attacks. Your doctor may also prescribe it for other purposes; ask your doctor if you are unsure."),
        ("h", "2. What you need to know before you take Lumexa"),
        ("p", "Do not take Lumexa if you are allergic to lumexatib or any of the other ingredients of this medicine (listed in section 6); if you are pregnant or breast-feeding; or if you have severe liver problems."),
        ("p", "Warnings and precautions: Talk to your doctor or pharmacist before taking Lumexa if you have kidney problems, a history of seizures, or low blood pressure. Regular blood tests may be needed during the first 12 weeks of treatment."),
    ])
    p1 += _stack("r", *Rr, 100, [
        ("h", "Other medicines and Lumexa"),
        ("p", "Tell your doctor or pharmacist if you are taking, have recently taken or might take any other medicines. In particular, do not take Lumexa with ketoconazole, clarithromycin or St John's wort."),
        ("h", "Driving and using machines"),
        ("p", "Lumexa may cause dizziness. Do not drive or use machines until you know how this medicine affects you."),
        ("h", "3. How to take Lumexa"),
        ("p", "Always take this medicine exactly as your doctor or pharmacist has told you. Check with your doctor or pharmacist if you are not sure. The recommended dose for adults is one 20 mg tablet once daily. Swallow the tablet whole with a glass of water, with or without food."),
    ])
    p1 += foot(1)

    p2 = [T("tbl_t", 30, 24, 390, "Recommended dose by patient group", 8, "arialbd")]
    cols = [30, 150, 210, 280, 390]
    rows = [("Patient group", "Dose", "Frequency", "Maximum per day"), ("Adults", "20 mg", "Once daily", "20 mg"),
            ("Elderly (65+ years)", "10 mg", "Once daily", "10 mg"), ("Adolescents 12-17 years", "10 mg", "Once daily", "10 mg"),
            ("Renal impairment", "10 mg", "Once daily", "10 mg")]
    top, rh = 40, 14
    for i in range(len(rows) + 1):
        p2.append(dict(id=f"hl{i}", kind="line", p0=(cols[0], top + i * rh), p1=(cols[-1], top + i * rh), color=GREY, width=0.5))
    for j, x in enumerate(cols):
        p2.append(dict(id=f"vl{j}", kind="line", p0=(x, top), p1=(x, top + len(rows) * rh), color=GREY, width=0.5))
    for i, row in enumerate(rows):
        for j, txt in enumerate(row):
            p2.append(T(f"c{i}{j}", cols[j] + 4, top + i * rh + 3, cols[j + 1] - 3, txt, 6.8, "arialbd" if i == 0 else "arial"))
    p2 += _stack("l", *L, 130, [
        ("h", "4. Possible side effects"),
        ("p", "Like all medicines, this medicine can cause side effects, although not everybody gets them."),
        ("p", "Common (may affect up to 1 in 10 people): headache, nausea, dizziness, tiredness."),
        ("p", "Uncommon (may affect up to 1 in 100 people): rash, palpitations, blurred vision."),
        ("p", "Rare (may affect up to 1 in 1,000 people): allergic reactions, seizures. Stop taking Lumexa and tell your doctor immediately if you get swelling of the face, lips or throat."),
    ])
    p2 += _stack("r", *Rr, 130, [
        ("h", "5. How to store Lumexa"),
        ("p", "Keep this medicine out of the sight and reach of children. Do not use this medicine after the expiry date which is stated on the carton and blister after EXP. Do not store above 30 °C. Store in the original package in order to protect from moisture."),
        ("h", "6. Contents of the pack and other information"),
        ("p", "Each film-coated tablet contains 20 mg lumexatib. The other ingredients are lactose monohydrate, microcrystalline cellulose, croscarmellose sodium, magnesium stearate and hypromellose."),
        ("p", "Marketing authorisation holder: Nordhaven Pharma GmbH, 12 Hafenstrasse, 20457 Hamburg, Germany."),
    ])
    p2 += foot(2)
    return design("leaflet", [page((420, 595), p1), page((420, 595), p2)])


# ── 6. blister foil, 110 x 60 mm, repeated small print ────────────────────
def blister():
    els = [R("foil", (4, 4, 308, 166), fill=(214, 218, 222), width=0),
           dict(id="perf", kind="line", p0=(10, 88), p1=(300, 88), color=(150, 156, 162), width=0.4)]
    blue = (20, 60, 140)
    for r, cy in enumerate((55, 122)):
        for i in range(7):
            cx = 36 + i * 40.5
            els.append(dict(id=f"cell{r}{i}", kind="circle", c=(cx, cy), r=15, fill=(232, 236, 240), stroke=(140, 148, 156), width=0.8))
            els.append(T(f"nm{r}{i}", cx - 20, cy - 31, cx + 20, "LUMEXA 20", 5.5, "arialbd", blue, align=1))
            els.append(T(f"lt{r}{i}", cx - 20, cy + 19, cx + 20, "LX4471 03/2029", 4, "arial", blue, align=1))
    els.append(TR("edge", (8, 10, 18, 160), "LUMEXA 20 mg tablets  ·  14 tablets  ·  Nordhaven Pharma GmbH", 5, "arialbd", blue, rotate=270))
    return design("blister", [page((312, 170), els)])


DESIGNS = {"syrup": syrup, "carton": carton, "vial": vial, "tube": tube, "leaflet": leaflet, "blister": blister}
