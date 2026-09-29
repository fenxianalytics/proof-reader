"""Work out which files belong together in a batch: reference + sample (+ approved text), from names alone.

Recognised, in order:
  1. a role word in the file name:   carton_12_reference.pdf / carton_12_sample.pdf / carton_12_approved_text.docx
  2. a role word in the folder name:  reference/carton_12.pdf  +  sample/carton_12.pdf
  3. versions of the same name:       carton_12_v3.pdf (reference) / carton_12_v4.pdf (sample)
Anything that can't be paired is returned as unpaired, never guessed.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

REF = {"reference", "ref", "approved", "master", "original", "orig", "old", "previous", "prev", "current", "artwork"}
SMP = {"sample", "proof", "new", "revised", "rev", "received", "supplier", "draft", "candidate", "print", "printer", "test"}
DECK = {"approvedtext", "copydeck", "copy", "deck", "text", "approved_text", "copytext", "leaflettext", "labeltext"}
TEXT_EXT = {".docx", ".txt"}
ARTWORK_EXT = {".pdf", ".jpg", ".jpeg", ".png"}


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[\s_\-.()\[\]]+", s.lower()) if t]


def classify(path: str) -> tuple[str | None, str, int | None]:
    """(role, key, version) for one file. role is 'ref' | 'sample' | 'deck' | None."""
    p = PurePosixPath(path.replace("\\", "/"))
    ext = p.suffix.lower()
    toks = _tokens(p.stem)
    joined = "".join(toks)
    folders = [t for part in p.parts[:-1] for t in _tokens(part)]
    role = None
    if ext in TEXT_EXT or any(t in DECK for t in toks) or "approvedtext" in joined or "copydeck" in joined:
        role = "deck"
    elif any(t in REF for t in toks):
        role = "ref"
    elif any(t in SMP for t in toks):
        role = "sample"
    elif any(t in REF for t in folders):
        role = "ref"
    elif any(t in SMP for t in folders):
        role = "sample"
    version = None
    keep = []
    for t in toks:
        m = re.fullmatch(r"v(\d+)|rev(\d+)|version(\d+)", t)
        if m:
            version = int(next(g for g in m.groups() if g))
            continue
        if t in REF or t in SMP or t in DECK or t in ("approved", "text"):
            continue
        keep.append(t)
    return role, "_".join(keep) or p.stem.lower(), version


def pair(paths: list[str]) -> dict:
    groups: dict[str, dict] = {}
    unpaired: list[str] = []
    for path in paths:
        role, key, ver = classify(path)
        g = groups.setdefault(key, dict(key=key, ref=None, sample=None, deck=None, versions=[]))
        if role in ("ref", "sample", "deck") and g[role] is None:
            g[role] = path
        elif role is None and PurePosixPath(path).suffix.lower() in ARTWORK_EXT and ver is not None:
            g["versions"].append((ver, path))
        else:
            unpaired.append(path)
    out = []
    for g in groups.values():
        vs = sorted(g.pop("versions"))
        if vs and g["ref"] is None and g["sample"] is None and len(vs) >= 2:
            g["ref"], g["sample"] = vs[-2][1], vs[-1][1]  # the newest version is checked against the one before it
            unpaired += [p for _, p in vs[:-2]]
        else:
            unpaired += [p for _, p in vs]
        if g["ref"] and g["sample"]:
            out.append(g)
        else:
            unpaired += [p for p in (g["ref"], g["sample"], g["deck"]) if p]
    out.sort(key=lambda g: g["key"])
    return dict(pairs=out, unpaired=sorted(set(unpaired)))
