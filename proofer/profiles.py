"""Tolerance profiles and variable-data rules.

A profile is a named set of Config overrides (how picky the comparison is). Variable-data labels name fields
that are EXPECTED to differ between two prints of the same artwork - lot / batch numbers, expiry and
manufacturing dates, serial numbers. A change right after one of those labels is reported as information
("variable data changed, as expected") instead of a defect, but only when that profile is chosen: when checking
new artwork against its approved version, a changed expiry date is a critical error and stays one.
"""
from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

from .compare import SEV_RANK, Config, Finding

SETTINGS = Path(__file__).resolve().parent.parent / "results" / "settings.json"

PRESETS = {
    "standard": dict(label="Standard", description="Balanced defaults, validated on the test sets. Use this unless there is a reason not to.",
                     overrides={}, variable=False, minor_as_info=False),
    "strict": dict(label="Strict", description="Artwork approval for regulated packs: smaller colour, position and size changes count.",
                   overrides=dict(delta_e=2.0, move_tol_mm=0.15, min_area_px=4, separation_tol=8.0, barcode_shift_mm=0.3), variable=False, minor_as_info=False),
    "lenient": dict(label="Lenient", description="Quick screening: small colour and layout drift is noted, not flagged.",
                    overrides=dict(delta_e=5.0, move_tol_mm=0.5, min_area_px=12, separation_tol=18.0), variable=False, minor_as_info=True),
    "print_run": dict(label="Print run check", description="Same artwork, new print run: lot, batch, expiry and serial fields are expected to differ.",
                      overrides={}, variable=True, minor_as_info=False),
}
DEFAULT_LABELS = ["Lot", "Lote", "Lotto", "Batch", "Batch No", "B.No", "Ch.-B", "Charge", "EXP", "Exp. Date", "Expiry", "Cad", "Scad",
                  "Mfg. Date", "Mfg", "MFD", "Best before", "SN", "Serial"]
TUNABLE = ("delta_e", "move_tol_mm", "min_area_px", "separation_tol", "barcode_shift_mm", "dpi")


def load() -> dict:
    try:
        s = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s = {}
    s.setdefault("profile", "standard")
    s.setdefault("overrides", {})
    s.setdefault("variable_labels", DEFAULT_LABELS)
    return s


def save(s: dict) -> dict:
    if s.get("profile") not in PRESETS:
        raise ValueError("unknown profile")
    clean = {k: float(v) for k, v in (s.get("overrides") or {}).items() if k in TUNABLE and v not in ("", None)}
    labels = [x.strip() for x in s.get("variable_labels", DEFAULT_LABELS) if str(x).strip()]
    out = dict(profile=s["profile"], overrides=clean, variable_labels=labels)
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def make_config(settings: dict, **extra) -> Config:
    p = PRESETS.get(settings.get("profile", "standard"), PRESETS["standard"])
    kw = dict(p["overrides"])
    kw.update({k: v for k, v in (settings.get("overrides") or {}).items() if k in TUNABLE})
    kw.update({k: v for k, v in extra.items() if v is not None})
    if "min_area_px" in kw:
        kw["min_area_px"] = int(kw["min_area_px"])
    if "dpi" in kw:
        kw["dpi"] = int(kw["dpi"])
    return dataclasses.replace(Config(), **kw)


def _label_rx(labels):
    alts = sorted((re.escape(l.rstrip(".:")).replace(r"\ ", r"\s*") for l in labels), key=len, reverse=True)
    return re.compile(r"(?i)(?<![\w])(?:" + "|".join(alts) + r")\.?\s*[:.#]?\s*")


def apply(findings: list[Finding], settings: dict) -> list[Finding]:
    """Post-process a proof's findings for the chosen profile: variable data -> info, and (lenient) minor -> info."""
    p = PRESETS.get(settings.get("profile", "standard"), PRESETS["standard"])
    rx = _label_rx(settings.get("variable_labels") or DEFAULT_LABELS) if p["variable"] else None
    for f in findings:
        if f.severity == "info":
            continue
        if rx is not None and f.category in ("text", "copydeck", "graphic", "barcode") and (f.a_text or f.b_text):
            ctx = " ".join(str(x) for x in (f.detail.get("context_a", ""), f.detail.get("context_b", ""), f.detail.get("context", ""),
                                            f.detail.get("ocr_a", ""), f.detail.get("ocr_b", ""), f.message))
            vals = [v for v in (f.a_text, f.b_text) if v]
            hit = False
            for m in rx.finditer(ctx):
                after = ctx[m.end():m.end() + 40]
                if any(after.startswith(v) or after.split(" ")[0] in v for v in vals):
                    hit = True
                    break
            if hit:
                f.detail["was"] = f.severity
                f.severity, f.kind = "info", "variable_data"
                f.message = "Variable data changed, as expected for a new print run: " + f.message
                continue
        if p["minor_as_info"] and f.severity == "minor":
            f.detail["was"] = "minor"
            f.severity = "info"
    return findings


def presets_public() -> list[dict]:
    return [dict(id=k, label=v["label"], description=v["description"], overrides=v["overrides"], variable=v["variable"],
                 minor_as_info=v["minor_as_info"]) for k, v in PRESETS.items()]


def defaults() -> dict:
    c = Config()
    return {k: getattr(c, k) for k in TUNABLE}


__all__ = ["PRESETS", "load", "save", "make_config", "apply", "presets_public", "defaults", "SEV_RANK"]
