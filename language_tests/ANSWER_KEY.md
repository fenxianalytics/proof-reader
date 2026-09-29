# Language test set

Fictional paracetamol leaflet in 8 languages. Reference = `reference.pdf`, sample = `sample.pdf` in each folder.
Translations are simple test strings, not certified. Rebuild with `python make_language_tests.py --build`.

| Case | Expected | What it tests |
|---|---|---|
| 01_en_vs_ru_wrong_language | language_mismatch | English reference, Cyrillic sample: whole page in the wrong script |
| 02_en_vs_el_wrong_language | language_mismatch | English reference, Greek sample |
| 03_en_vs_zh_wrong_language | language_mismatch | English reference, Chinese sample |
| 04_en_vs_ar_wrong_language | language_mismatch | English reference, Arabic sample |
| 05_fr_vs_es_same_script | any_finding | French reference, Spanish sample: same alphabet. Known gap: no language_mismatch finding, only a pile of text changes |
| 06_en_vs_de_same_script | any_finding | English reference, German sample: same alphabet, same known gap |
| 07_ru_clean_control | pass | Identical Russian pair: must be silent |
| 08_ru_strength_changed | text_changed | Russian: strength 500 -> 300 mg |
| 09_ru_limit_changed | text_changed | Russian: max tablets 4 -> 8 |
| 10_ru_meaning_reversed | text_changed | Russian: 'do not use' -> 'may use' (correct spelling both ways) |
| 11_ru_typo | text_changed | Russian: letter changed in the product name (no Russian spell-check exists) |
| 12_ru_flattened_strength | any_finding | Russian, sample flattened to image: strength changed. Tests OCR on Cyrillic |
| 13_ru_flattened_clean_control | pass | Russian, flattened but unchanged: must not raise false alarms |
| 14_el_strength_changed | text_changed | Greek: strength changed |
| 15_zh_clean_control | pass | Identical Chinese pair: must be silent |
| 16_zh_meaning_reversed | text_changed | Chinese: 'do not use' -> 'may use' |
| 17_ar_strength_changed | text_changed | Arabic: strength changed (tests right-to-left text) |
| 18_de_dose_changed | text_changed | German: dosing interval changed (control for the Latin-script path) |
