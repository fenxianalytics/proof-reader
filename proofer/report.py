"""Report assembly, shared by the web app and the standalone HTML export.

A proof is described by one JSON payload (verdict, findings, coverage, page geometry, image URLs). The
browser UI in proofer/web renders it. The web app serves the images from disk; the standalone export
embeds them as data URIs, so a single .html file is a complete, offline, shareable proof report.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from . import __version__, ocr
from .compare import Config, Result
from .explain import explain

WEB = Path(__file__).parent / "web"
SHOW_DPI = 150


def _png(img_rgb: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_PNG_COMPRESSION, 4])
    return buf.tobytes()


def _overlay(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ia, ib = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY) < 170, cv2.cvtColor(b, cv2.COLOR_RGB2GRAY) < 170
    out = np.full(a.shape, 255, np.uint8)
    out[ia & ib] = (170, 170, 170)
    out[ia & ~ib] = (211, 47, 47)   # only in reference
    out[ib & ~ia] = (25, 118, 210)  # only in sample
    return out


def _fit(a: np.ndarray, b: np.ndarray):
    h, w = max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])
    res = []
    for im in (a, b):
        c = np.full((h, w, 3), 255, np.uint8)
        c[: im.shape[0], : im.shape[1]] = im
        res.append(c)
    return res


def page_assets(pg: dict, show_dpi: int = SHOW_DPI) -> dict:
    """PNG bytes for reference / sample / overlay at a screen-friendly resolution, plus the page size in points."""
    dpi = pg["dpi"]
    rs = lambda im: cv2.resize(im, (int(im.shape[1] * show_dpi / dpi), int(im.shape[0] * show_dpi / dpi)), interpolation=cv2.INTER_AREA)
    a, b = _fit(rs(pg["img_a"]), rs(pg["img_b"]))
    return dict(ref=_png(a), sample=_png(b), overlay=_png(_overlay(a, b)), w_pt=a.shape[1] * 72 / show_dpi, h_pt=a.shape[0] * 72 / show_dpi)


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_payload(result: Result, name_a: str, name_b: str, cfg: Config, assets: list[dict], url, meta: dict | None = None) -> dict:
    """`url(page_index, kind)` -> where the browser fetches that image (an API path, or a data URI)."""
    d = result.to_dict()
    findings = []
    for f, raw in zip(result.findings, d["findings"]):
        raw["why"] = explain(f, cfg)
        findings.append(raw)
    return dict(
        names=dict(ref=name_a, sample=name_b),
        created=datetime.now().isoformat(timespec="seconds"),
        engine=dict(version=__version__, dpi=cfg.dpi, ocr=bool(cfg.ocr and ocr.available())),
        verdict=d["verdict"], counts=d["counts"], coverage_limited=d["coverage_limited"],
        coverage=d["coverage"], attention=d["attention"], warnings=d["warnings"],
        findings=findings,
        pages=[dict(index=pg["page"], sample_page=pg.get("sample_page", pg["page"]), w_pt=a["w_pt"], h_pt=a["h_pt"],
                    H=pg.get("H"), aligned=bool(pg.get("aligned")),
                    img={k: url(pg["page"], k) for k in ("ref", "sample", "overlay")})
               for pg, a in zip(result.pages, assets)],
        meta=meta or {},
    )


def dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o))


def findings_csv(payload: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "page", "severity", "confidence", "category", "kind", "message", "reference", "sample", "decision", "note"])
    for f in payload["findings"]:
        if f["severity"] == "info":
            continue
        rv = (payload.get("reviews") or {}).get(str(f["id"]), {})
        w.writerow([f["id"], f["page"] + 1, f["severity"], f["confidence"], f["category"], f["kind"], f["message"],
                    f["a_text"], f["b_text"], rv.get("decision", ""), rv.get("note", "")])
    return buf.getvalue()


def render_standalone(payload: dict) -> str:
    """The web UI with its stylesheet, script and data inlined: one offline file."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "app.css").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    data = dumps(payload).replace("</", "<\\/")
    logo = "data:image/png;base64," + base64.b64encode((WEB / "logo.png").read_bytes()).decode()
    js = js.replace("/static/logo.png", logo)
    html = html.replace("/static/logo.png", logo)
    html = html.replace('<link rel="stylesheet" href="/static/app.css">', f"<style>{css}</style>")
    html = html.replace('<script src="/static/app.js"></script>', f"<script>window.__PROOF__={data};</script><script>{js}</script>")
    return html


def build_html(result: Result, name_a: str, name_b: str, show_dpi: int = SHOW_DPI, cfg: Config | None = None, meta: dict | None = None,
               deck_name: str = "") -> str:
    cfg = cfg or Config()
    assets = [page_assets(pg, show_dpi) for pg in result.pages]
    uri = lambda i, kind: "data:image/png;base64," + base64.b64encode(assets[[p["page"] for p in result.pages].index(i)][kind]).decode()
    payload = build_payload(result, name_a, name_b, cfg, assets, uri, meta)
    payload["names"]["deck"] = deck_name
    return render_standalone(payload)
