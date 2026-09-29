"""Spell check of the sample artwork.

A word is accepted when it is in any loaded language dictionary, in the product dictionary (dictionary.txt at
the project root: brand names, INNs, excipients - one word per line), in the reference artwork, or in the
approved text. Only NEW unknown words in the sample become findings; unknown words that the approved
reference already contains (typically brand and drug names) are listed in the coverage report instead, so a
clean file stays clean.
"""
from __future__ import annotations

import re
from pathlib import Path

LANGS = ("en", "fr", "de", "es", "it", "pt", "nl")
PRODUCT_DICT = Path(__file__).resolve().parent.parent / "dictionary.txt"
WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")
_checkers = None


def _get():
    global _checkers
    if _checkers is None:
        try:
            from spellchecker import SpellChecker
            _checkers = [SpellChecker(language=l, distance=1) for l in LANGS]
        except Exception:
            _checkers = []
    return _checkers


def available() -> bool:
    return bool(_get())


def product_words() -> set[str]:
    if not PRODUCT_DICT.exists():
        return set()
    return {w.strip().casefold() for w in PRODUCT_DICT.read_text(encoding="utf-8").splitlines() if w.strip() and not w.startswith("#")}


def words(text: str) -> list[str]:
    return WORD.findall(text.replace("’", "'"))


LATIN = re.compile(r"[A-Za-zÀ-ɏ']+")


def checkable(w: str) -> bool:
    # short words, all-caps tokens (acronyms, batch codes, brand wordmarks) and non-Latin scripts (Chinese,
    # Arabic, Cyrillic... - no dictionary loaded for them) are not spell-checked
    return len(w) >= 4 and not w.isupper() and bool(LATIN.fullmatch(w))


def is_known(w: str, extra: set[str]) -> bool:
    lw = w.casefold()
    if lw in extra:
        return True
    parts = [lw] + ([lw.split("'")[-1]] if "'" in lw else [])
    return any(c.known(parts) for c in _get())


def suggest(w: str) -> str | None:
    cs = _get()
    if not cs:
        return None
    try:
        s = cs[0].correction(w.casefold())
    except Exception:
        return None
    return s if s and s != w.casefold() else None
