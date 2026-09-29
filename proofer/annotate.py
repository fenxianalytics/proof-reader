"""Annotated PDF: the sample file itself, with every finding drawn on it as a real PDF comment.

Opens in Acrobat / Preview / any PDF viewer: a numbered box per finding in its severity colour, the message and
the reason in the comment pop-up, and a summary page at the front (verdict, counts, coverage, reviewer decisions,
file hashes). The original page content is untouched; only annotations and the summary page are added.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pymupdf

from .imaging import open_pdf

COL = {"critical": (0.9, 0.16, 0.11), "major": (0.88, 0.48, 0.0), "minor": (0.72, 0.53, 0.04), "info": (0.48, 0.48, 0.53), "mark": (0.48, 0.36, 0.96)}


def _inv_map(H, r):
    if H is None or not r:
        return r
    Hi = np.linalg.inv(np.array(H, dtype=float))
    xs, ys = [], []
    for x, y in ((r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])):
        v = Hi @ np.array([x, y, 1.0])
        xs.append(v[0] / v[2]); ys.append(v[1] / v[2])
    return [min(xs), min(ys), max(xs), max(ys)]


def build(sample_pdf: str, payload: dict) -> bytes:
    doc = open_pdf(sample_pdf)
    pages = {pg["index"]: pg for pg in payload["pages"]}
    reviews = payload.get("reviews") or {}
    for f in payload["findings"]:
        if f["severity"] == "info" and f["kind"] != "variable_data":
            continue
        pg = pages.get(f["page"])
        if pg is None:
            continue
        spage = pg.get("sample_page", f["page"])
        if spage >= len(doc):
            continue
        box = f.get("bbox_b") or f.get("bbox_a")
        if not box:
            continue
        # findings are reported in the reference's frame; a registered page is mapped back onto the sample's own
        r = pymupdf.Rect(_inv_map(pg.get("H"), box)) + (-2, -2, 2, 2)
        page = doc[spage]
        r = r & page.rect
        if r.is_empty:
            continue
        rv = reviews.get(str(f["id"]), {})
        a = page.add_rect_annot(r)
        a.set_colors(stroke=COL["mark"])
        a.set_border(width=1.4)
        a.set_opacity(0.9)
        status = f" [{rv['decision']}{' by ' + rv['reviewer'] if rv.get('reviewer') else ''}]" if rv.get("decision", "pending") != "pending" else ""
        a.set_info(title=f"#{f['id']} {f['severity'].upper()} {f['category']}/{f['kind']}{status}",
                   content=f"{f['message']}\n\nWhy: {f.get('why', '')}" + (f"\n\nReviewer note: {rv['note']}" if rv.get("note") else ""))
        a.update()
        lab = pymupdf.Rect(r.x0, max(0, r.y0 - 9), r.x0 + 6 + 5 * len(str(f["id"])), max(9, r.y0))
        t = page.add_freetext_annot(lab, str(f["id"]), fontsize=6.5, text_color=(1, 1, 1), fill_color=COL["mark"], align=1)
        t.set_info(title=f"#{f['id']}", content=f["message"])
        t.update()
    # summary page at the front
    sp = doc.new_page(0, width=595, height=842)
    c, y = payload["counts"], 60
    so = payload.get("signoff")

    def line(txt, size=10, font="helv", color=(0, 0, 0), gap=6):
        nonlocal y
        txt = txt.replace("→", "->").replace("²", "2").replace("≥", ">=").replace("≤", "<=")  # base-14 fonts lack these
        rc = sp.insert_textbox(pymupdf.Rect(50, y, 545, y + 400), txt, fontsize=size, fontname=font, color=color)
        used = 400 - rc if rc >= 0 else 400
        y += min(used, 400) + gap

    line("Proof report", 20, "hebo", gap=2)
    line(f"Sample: {payload['names']['sample']}    Reference: {payload['names']['ref']}"
         + (f"    Approved text: {payload['names'].get('deck')}" if payload["names"].get("deck") else ""), 8.5, color=(0.35, 0.35, 0.4))
    line(f"Verdict: {payload['verdict']}    {c['critical'] + c['major'] + c['minor']} findings", 12, "hebo",
         COL["critical"] if payload["verdict"] == "FAIL" else COL["major"] if payload["verdict"] == "REVIEW" else (0.05, 0.55, 0.35))
    if so:
        line(f"Sign-off: {so['outcome'].upper()} by {so['reviewer']} on {so['ts']}" + (f" - {so['note']}" if so.get("note") else ""), 10, "hebo")
    line("Findings (boxes on the following pages; open a box to read the full comment):", 9, "hebo")
    for f in payload["findings"]:
        if f["severity"] == "info" and f["kind"] != "variable_data":
            continue
        rv = reviews.get(str(f["id"]), {}).get("decision", "")
        line(f"#{f['id']}  {f['severity'].upper():8}  p{f['page'] + 1}  {f['message'][:170]}" + (f"  [{rv}]" if rv and rv != "pending" else ""), 7.5, gap=2)
        if y > 780:
            break
    for a in payload.get("attention", [])[:6]:
        line("Worth a look: " + a["message"][:200], 7.5, color=(0.5, 0.35, 0.0), gap=2)
    sh = (payload.get("meta") or {}).get("sha256", {})
    line("", 4)
    line(f"Engine v{payload['engine']['version']} · {payload['engine'].get('profile', 'Standard')} profile · {payload['engine']['dpi']} dpi · "
         f"generated {datetime.now().strftime('%Y-%m-%d %H:%M')}\nSHA-256 reference {sh.get('ref', 'n/a')}\nSHA-256 sample {sh.get('sample', 'n/a')}",
         6.5, color=(0.45, 0.45, 0.5))
    return doc.tobytes(garbage=1, deflate=True)
