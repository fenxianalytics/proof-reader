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
NL = b"\n"
_lists = None  # one sorted, newline-separated UTF-8 word list per language (a few MB in all, not ~150 MB of dicts)
_en = None     # the full English checker: only needed for "did you mean" suggestions, so loaded on first use


def _get():
    """Word lists for every language, built once from the library's own dictionaries (one language at a time, so the
    full dictionaries are never all in memory together). A word is kept only if the library itself would check it."""
    global _lists
    if _lists is None:
        try:
            from spellchecker import SpellChecker
            lists = []
            for lang in LANGS:
                chk = SpellChecker(language=lang, distance=1)
                # plain alphabetic words are always checked, except the two that Python reads as a number ("inf", "infinity")
                words = sorted(w for w in chk.word_frequency.dictionary
                               if "\n" not in w and ((w.isalpha() and w not in ("inf", "infinity")) or chk._check_if_should_check(w)))
                lists.append(("\n".join(words) + "\n").encode("utf-8"))
                del chk
            _lists = lists
        except Exception:
            _lists = []
    return _lists


def _in_list(blob: bytes, w: str) -> bool:
    """Is w a line of this sorted, newline-terminated word list? (binary search)"""
    key = w.encode("utf-8")
    lo, hi = 0, len(blob)  # invariant: lo is the start of a line, hi the end of one
    while lo < hi:
        mid = (lo + hi) // 2
        start = blob.rfind(NL, lo, mid) + 1 if mid > lo else lo
        start = max(start, lo)
        end = blob.find(NL, mid, hi)
        end = hi if end < 0 else end
        line = blob[start:end]
        if line == key:
            return True
        if line < key:
            lo = end + 1
        else:
            hi = start
    return False


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
    return any(_in_list(blob, part.lower()) for blob in _get() for part in parts)


def suggest(w: str) -> str | None:
    global _en
    if not _get():
        return None
    try:
        if _en is None:
            from spellchecker import SpellChecker
            _en = SpellChecker(language=LANGS[0], distance=1)
        s = _en.correction(w.casefold())
    except Exception:
        return None
    return s if s and s != w.casefold() else None
