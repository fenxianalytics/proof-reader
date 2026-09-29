"""Build and run the language test set -> language_tests/

    python make_language_tests.py          # build the pairs + ANSWER_KEY.md, then run each pair and print a scorecard
    python make_language_tests.py --build  # build only

Each pair is a one-page fictional leaflet (paracetamol, batch/expiry line) rendered from the same text in
English, Russian, Greek, Chinese, Arabic, French, Spanish and German. The translations are simple hand-written
test strings, NOT certified translations. Arabic is written without letter shaping (fine for a text-diff test).

Every case states what the proofer SHOULD do (`expect`), so the scorecard shows what works and what does not.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).parent
OUT = ROOT / "language_tests"
FONTS = Path("C:/Windows/Fonts")
LATIN = FONTS / "arial.ttf"      # covers Latin, Cyrillic, Greek, Arabic
CJK = FONTS / "msyh.ttc"

TEXT = {
    "en": ["PARACETAMOL TABLETS 500 mg",
           "Dosage: adults take 1 tablet every 6 hours. Do not exceed 4 tablets in 24 hours.",
           "Warning: keep out of the reach of children. Do not use if the seal is broken.",
           "Store below 25 °C in the original package.",
           "Batch: LX4471   Exp: 03/2028"],
    "ru": ["ТАБЛЕТКИ ПАРАЦЕТАМОЛ 500 мг",
           "Дозировка: взрослым по 1 таблетке каждые 6 часов. Не превышать 4 таблетки в сутки.",
           "Предупреждение: хранить в недоступном для детей месте. Не использовать, если упаковка повреждена.",
           "Хранить при температуре не выше 25 °C в оригинальной упаковке.",
           "Серия: LX4471   Годен до: 03/2028"],
    "el": ["ΔΙΣΚΙΑ ΠΑΡΑΚΕΤΑΜΟΛΗΣ 500 mg",
           "Δοσολογία: ενήλικες 1 δισκίο κάθε 6 ώρες. Μην υπερβαίνετε τα 4 δισκία σε 24 ώρες.",
           "Προειδοποίηση: φυλάσσετε μακριά από παιδιά. Μη χρησιμοποιείτε αν η σφράγιση έχει σπάσει.",
           "Φυλάσσεται κάτω από 25 °C στην αρχική συσκευασία.",
           "Παρτίδα: LX4471   Λήξη: 03/2028"],
    "zh": ["对乙酰氨基酚片 500 mg",
           "用法用量:成人每6小时服1片,24小时内不超过4片。",
           "警告:请放在儿童接触不到的地方。包装破损请勿使用。",
           "25 °C以下原包装保存。",
           "批号:LX4471   有效期:03/2028"],
    "ar": ["أقراص باراسيتامول 500 ملغ",
           "الجرعة: للبالغين قرص واحد كل 6 ساعات. لا تتجاوز 4 أقراص خلال 24 ساعة.",
           "تحذير: يحفظ بعيدا عن متناول الأطفال. لا تستخدم إذا كان الختم مكسورا.",
           "يحفظ في درجة حرارة أقل من 25 °م في العبوة الأصلية.",
           "الدفعة: LX4471   الانتهاء: 03/2028"],
    "fr": ["COMPRIMÉS DE PARACÉTAMOL 500 mg",
           "Posologie : adultes, 1 comprimé toutes les 6 heures. Ne pas dépasser 4 comprimés par 24 heures.",
           "Avertissement : tenir hors de la portée des enfants. Ne pas utiliser si le sceau est brisé.",
           "Conserver à une température inférieure à 25 °C dans l'emballage d'origine.",
           "Lot : LX4471   Exp : 03/2028"],
    "es": ["COMPRIMIDOS DE PARACETAMOL 500 mg",
           "Posología: adultos, 1 comprimido cada 6 horas. No exceder 4 comprimidos en 24 horas.",
           "Advertencia: mantener fuera del alcance de los niños. No usar si el sello está roto.",
           "Conservar por debajo de 25 °C en el envase original.",
           "Lote: LX4471   Cad: 03/2028"],
    "de": ["PARACETAMOL TABLETTEN 500 mg",
           "Dosierung: Erwachsene 1 Tablette alle 6 Stunden. Nicht mehr als 4 Tabletten in 24 Stunden einnehmen.",
           "Warnung: Für Kinder unzugänglich aufbewahren. Nicht verwenden, wenn das Siegel gebrochen ist.",
           "Unter 25 °C in der Originalverpackung lagern.",
           "Charge: LX4471   Verwendbar bis: 03/2028"],
}

# (name, ref lang, sample lang, edits to the sample [(old, new)], flatten sample, expect, what we are testing)
CASES = [
    ("01_en_vs_ru_wrong_language", "en", "ru", [], False, "language_mismatch", "English reference, Cyrillic sample: whole page in the wrong script"),
    ("02_en_vs_el_wrong_language", "en", "el", [], False, "language_mismatch", "English reference, Greek sample"),
    ("03_en_vs_zh_wrong_language", "en", "zh", [], False, "language_mismatch", "English reference, Chinese sample"),
    ("04_en_vs_ar_wrong_language", "en", "ar", [], False, "language_mismatch", "English reference, Arabic sample"),
    ("05_fr_vs_es_same_script", "fr", "es", [], False, "any_finding", "French reference, Spanish sample: same alphabet. Known gap: no language_mismatch finding, only a pile of text changes"),
    ("06_en_vs_de_same_script", "en", "de", [], False, "any_finding", "English reference, German sample: same alphabet, same known gap"),
    ("07_ru_clean_control", "ru", "ru", [], False, "pass", "Identical Russian pair: must be silent"),
    ("08_ru_strength_changed", "ru", "ru", [("500 мг", "300 мг")], False, "text_changed", "Russian: strength 500 -> 300 mg"),
    ("09_ru_limit_changed", "ru", "ru", [("Не превышать 4", "Не превышать 8")], False, "text_changed", "Russian: max tablets 4 -> 8"),
    ("10_ru_meaning_reversed", "ru", "ru", [("Не использовать,", "Можно использовать,")], False, "text_changed", "Russian: 'do not use' -> 'may use' (correct spelling both ways)"),
    ("11_ru_typo", "ru", "ru", [("ПАРАЦЕТАМОЛ", "ПАРАЦЕТОМОЛ")], False, "text_changed", "Russian: letter changed in the product name (no Russian spell-check exists)"),
    ("12_ru_flattened_strength", "ru", "ru", [("500 мг", "300 мг")], True, "any_finding", "Russian, sample flattened to image: strength changed. Tests OCR on Cyrillic"),
    ("13_ru_flattened_clean_control", "ru", "ru", [], True, "pass", "Russian, flattened but unchanged: must not raise false alarms"),
    ("14_el_strength_changed", "el", "el", [("500 mg", "300 mg")], False, "text_changed", "Greek: strength changed"),
    ("15_zh_clean_control", "zh", "zh", [], False, "pass", "Identical Chinese pair: must be silent"),
    ("16_zh_meaning_reversed", "zh", "zh", [("请勿使用", "可以使用")], False, "text_changed", "Chinese: 'do not use' -> 'may use'"),
    ("17_ar_strength_changed", "ar", "ar", [("500", "300")], False, "text_changed", "Arabic: strength changed (tests right-to-left text)"),
    ("18_de_dose_changed", "de", "de", [("alle 6 Stunden", "alle 4 Stunden")], False, "text_changed", "German: dosing interval changed (control for the Latin-script path)"),
]


def _page(lines: list[str], lang: str, path: Path):
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=300)
    fontfile = CJK if lang == "zh" else LATIN
    y = 30
    for i, line in enumerate(lines):
        size = 15 if i == 0 else 10
        h = 22 if i == 0 else 46
        page.insert_textbox(pymupdf.Rect(28, y, 392, y + h), line, fontname="F0", fontfile=str(fontfile), fontsize=size,
                            align=2 if lang == "ar" else 0)
        y += h + 6
    doc.save(path)
    doc.close()


def _flatten(src: Path, dst: Path, dpi=300):
    d = pymupdf.open(src)
    pix = d[0].get_pixmap(dpi=dpi, alpha=False)
    out = pymupdf.open()
    p = out.new_page(width=d[0].rect.width, height=d[0].rect.height)
    p.insert_image(p.rect, pixmap=pix)
    out.save(dst)
    out.close()
    d.close()


def build():
    OUT.mkdir(exist_ok=True)
    key = []
    for name, ra, sa, edits, flat, expect, what in CASES:
        d = OUT / name
        d.mkdir(exist_ok=True)
        _page(TEXT[ra], ra, d / "reference.pdf")
        lines = list(TEXT[sa])
        for old, new in edits:
            assert any(old in l for l in lines), f"{name}: '{old}' not in the sample text"
            lines = [l.replace(old, new) for l in lines]
        tmp = d / "_sample_live.pdf"
        _page(lines, sa, tmp)
        if flat:
            _flatten(tmp, d / "sample.pdf")
            tmp.unlink()
        else:
            tmp.replace(d / "sample.pdf")
        key.append(dict(name=name, reference=ra, sample=sa, expect=expect, note=what))
    (OUT / "answer_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False), encoding="utf-8")
    md = ["# Language test set", "", "Fictional paracetamol leaflet in 8 languages. Reference = `reference.pdf`, sample = `sample.pdf` in each folder.",
          "Translations are simple test strings, not certified. Rebuild with `python make_language_tests.py --build`.", "",
          "| Case | Expected | What it tests |", "|---|---|---|"]
    md += [f"| {k['name']} | {k['expect']} | {k['note']} |" for k in key]
    (OUT / "ANSWER_KEY.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"built {len(CASES)} pairs in {OUT}")


def run():
    from proofer import Config, compare
    key = json.loads((OUT / "answer_key.json").read_text(encoding="utf-8"))
    ok = 0
    print(f"\n{'case':34} {'expected':18} {'verdict':7} result   findings")
    for k in key:
        d = OUT / k["name"]
        r = compare(str(d / "reference.pdf"), str(d / "sample.pdf"), Config(), keep_images=False)
        real = [f for f in r.findings if f.severity != "info"]
        kinds = [f"{f.category}/{f.kind}" for f in real]
        e = k["expect"]
        good = {"pass": not real,
                "language_mismatch": any(f.kind == "language_mismatch" for f in real),
                "text_changed": any(f.category == "text" and f.kind in ("changed", "removed", "added") for f in real),
                "any_finding": bool(real)}[e]
        ok += good
        print(f"{k['name']:34} {e:18} {r.verdict:7} {'OK  ' if good else 'FAIL'}     {len(real)}: {', '.join(sorted(set(kinds)))[:90]}")
    print(f"\n{ok}/{len(key)} cases behaved as expected")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    build()
    if "--build" not in sys.argv:
        run()
