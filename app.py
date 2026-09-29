"""Local web app for packaging-proofer.

    pip install -r requirements.txt
    python app.py
    open http://127.0.0.1:8000

Drop in the approved reference and the received sample; review every finding on a synced viewer, accept or
reject each one, and sign the proof off. Everything stays on this machine (results/jobs/).
"""
from __future__ import annotations

import base64
import datetime
import json
import os
import re
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from proofer import __version__, jobs, ocr
from proofer.imaging import is_image, is_pdf, to_pdf_bytes
from proofer.report import findings_csv, render_standalone

ROOT = Path(__file__).parent
WEB = ROOT / "proofer" / "web"
SAMPLES_DIR = ROOT / "samples"
EXAMPLES_DIR = ROOT / "examples"
RESULTS_DIR = ROOT / "results"
MAX_UPLOAD = 200 * 1024 * 1024

app = FastAPI(title="packaging-proofer", version=__version__)
app.mount("/static", StaticFiles(directory=WEB), name="static")


def _job(job_id: str) -> str:
    try:
        jobs.job_dir(job_id)
    except KeyError:
        raise HTTPException(404, "No such proof") from None
    return job_id


def _load_pairs() -> list[dict]:
    """Built-in examples: the committed examples/ folder (showcase, extreme, languages) plus, when present locally,
    the generated samples/ set."""
    out = []
    p = EXAMPLES_DIR / "index.json"
    if p.exists():
        out += json.loads(p.read_text(encoding="utf-8"))["pairs"]
    p = SAMPLES_DIR / "answer_key.json"
    if p.exists():
        out += json.loads(p.read_text(encoding="utf-8"))["pairs"]
    return out


async def _pdf(up: UploadFile, label: str) -> bytes:
    """Reference/sample upload as PDF bytes. A JPG or PNG is wrapped into a one-page PDF: the rest of the
    pipeline then treats it exactly like a scanned, image-only PDF (visual + OCR, no text layer)."""
    data = await up.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"{label} is larger than {MAX_UPLOAD // 2**20} MB")
    if is_pdf(data):
        return data
    if is_image(data):
        return to_pdf_bytes(data)
    raise HTTPException(400, f"{label} must be a PDF, JPG or PNG file")


@app.get("/")
def index() -> Response:
    # version the static assets by modification time so a browser never runs a stale script after an update
    v = int(max((WEB / f).stat().st_mtime for f in ("app.js", "app.css")))
    html = (WEB / "index.html").read_text(encoding="utf-8")
    html = html.replace("/static/app.js", f"/static/app.js?v={v}").replace("/static/app.css", f"/static/app.css?v={v}")
    return Response(html, media_type="text/html", headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def health() -> dict:
    from proofer import spelling
    return dict(version=__version__, ocr=ocr.available(), spelling=spelling.available())


@app.get("/api/samples")
def samples() -> list[dict]:
    out = []
    for p in _load_pairs():
        out.append(dict(name=p["name"], design=p.get("design", "syrup"), kind=p["kind"], note=p.get("note", ""),
                        description="; ".join(d["description"] for d in p["defects"]) or "Control: should show no differences"))
    return out


@app.post("/api/jobs")
async def create_job(reference: UploadFile = File(...), sample: UploadFile = File(...), dpi: int = Form(300), ocr_on: bool = Form(True),
                     deck: UploadFile | None = File(None), batch: str = Form(""), key: str = Form("")) -> dict:
    ref, smp = await _pdf(reference, "Reference"), await _pdf(sample, "Sample")
    dpi = max(72, min(600, dpi))
    deck_bytes, deck_name = None, ""
    if deck is not None and deck.filename:
        deck_name = deck.filename
        if Path(deck_name).suffix.lower() not in (".docx", ".txt", ".pdf"):
            raise HTTPException(400, "Approved text must be a .docx, .txt or .pdf file")
        deck_bytes = await deck.read()
    if batch:
        try:
            jobs.batch(batch)
        except KeyError:
            raise HTTPException(404, "No such batch") from None
    return dict(id=jobs.create(ref, smp, reference.filename or "reference.pdf", sample.filename or "sample.pdf", dpi, ocr_on, deck_bytes, deck_name,
                               batch=batch, key=key))


# ── batches ───────────────────────────────────────────────────────────────
class PairingReq(BaseModel):
    paths: list[str]


@app.post("/api/pairing")
def pairing(req: PairingReq) -> dict:
    from proofer.pairing import pair
    return pair(req.paths)


class BatchReq(BaseModel):
    name: str = ""
    unpaired: list[str] = []


@app.post("/api/batches")
def create_batch(req: BatchReq) -> dict:
    return dict(id=jobs.create_batch(req.name, req.unpaired))


@app.get("/api/batches")
def list_batches() -> list[dict]:
    return jobs.batches()


def _batch(bid: str) -> dict:
    try:
        return jobs.batch(bid)
    except KeyError:
        raise HTTPException(404, "No such batch") from None


@app.get("/api/batches/{bid}")
def get_batch(bid: str) -> dict:
    return _batch(bid)


@app.delete("/api/batches/{bid}")
def delete_batch(bid: str) -> dict:
    _batch(bid)
    jobs.delete_batch(bid)
    return dict(deleted=bid)


def _safe(name: str) -> str:
    return re.sub(r"[^\w\-]+", "_", name)[:60] or "item"


@app.get("/api/batches/{bid}/export.{fmt}")
def export_batch(bid: str, fmt: str) -> Response:
    import csv
    import io
    import zipfile
    b = _batch(bid)
    done = [r for r in b["rows"] if r["state"] == "done"]
    stem = _safe(b["name"])
    summary = io.StringIO()
    w = csv.writer(summary)
    w.writerow(["pair", "sample", "reference", "approved_text", "verdict", "findings", "reviewed", "signoff"])
    for r in b["rows"]:
        c = r.get("counts") or {}
        w.writerow([r["key"], r["names"]["sample"], r["names"]["ref"], r["names"].get("deck", ""), r.get("verdict", r["state"]),
                    sum(c.get(k, 0) for k in ("critical", "major", "minor")) if c else "", r["reviewed"], r.get("signoff") or ""])
    if fmt == "csv":
        allf = io.StringIO()
        fw = csv.writer(allf)
        fw.writerow(["pair", "id", "page", "severity", "confidence", "category", "kind", "message", "reference", "sample", "decision"])
        for r in done:
            p = jobs.payload(r["id"])
            for f in p["findings"]:
                if f["severity"] != "info":
                    fw.writerow([r["key"], f["id"], f["page"] + 1, f["severity"], f["confidence"], f["category"], f["kind"], f["message"],
                                 f["a_text"], f["b_text"], p["reviews"].get(str(f["id"]), {}).get("decision", "")])
        return Response(allf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{stem}_findings.csv"'})
    if fmt == "zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("summary.csv", summary.getvalue())
            for r in done:
                z.writestr(f"{_safe(r['key'])}.html", job_export(r["id"], "html").body)
        return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{stem}_reports.zip"'})
    raise HTTPException(404)


class SampleReq(BaseModel):
    pair: str
    with_deck: bool = True


@app.post("/api/jobs/sample")
def create_sample_job(req: SampleReq) -> dict:
    rec = next((p for p in _load_pairs() if p["name"] == req.pair), None)
    if rec is None:
        raise HTTPException(404, "Unknown example")
    if rec.get("base") == "examples":
        ref, smp = EXAMPLES_DIR / rec["a"], EXAMPLES_DIR / rec["b"]
        deck = EXAMPLES_DIR / rec["deck"] if rec.get("deck") else None
        use = req.with_deck and deck is not None and deck.exists()
        return dict(id=jobs.create(ref.read_bytes(), smp.read_bytes(), "reference.pdf", "sample.pdf",
                                   deck=deck.read_bytes() if use else None, deck_name="approved_text.docx" if use else ""))
    ref, smp = SAMPLES_DIR / rec["a"], SAMPLES_DIR / rec["b"]
    deck = SAMPLES_DIR / "decks" / f"{rec.get('design', 'syrup')}.docx"
    use = req.with_deck and deck.exists()
    return dict(id=jobs.create(ref.read_bytes(), smp.read_bytes(), Path(rec["a"]).name, Path(rec["b"]).name,
                               deck=deck.read_bytes() if use else None, deck_name=f"{rec.get('design', 'syrup')}_approved_text.docx" if use else ""))


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return jobs.listing()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    return jobs.status(_job(job_id))


@app.get("/api/jobs/{job_id}/report")
def job_report(job_id: str) -> dict:
    try:
        return jobs.payload(_job(job_id))
    except KeyError:
        raise HTTPException(409, "This proof isn't finished yet") from None


@app.get("/api/jobs/{job_id}/pages/{index}/{kind}.png")
def job_page(job_id: str, index: int, kind: str) -> FileResponse:
    if kind not in ("ref", "sample", "overlay"):
        raise HTTPException(404)
    p = jobs.job_dir(_job(job_id)) / "pages" / f"{index}_{kind}.png"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


class ReviewReq(BaseModel):
    finding: int
    decision: str
    note: str = ""
    reviewer: str = ""


@app.post("/api/jobs/{job_id}/review")
def job_review(job_id: str, req: ReviewReq) -> dict:
    try:
        jobs.review(_job(job_id), req.finding, req.decision, req.note, req.reviewer)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return dict(reviews=jobs.reviews(job_id), audit=jobs.audit(job_id))


class SignoffReq(BaseModel):
    outcome: str
    reviewer: str
    note: str = ""
    acknowledged_limits: bool = False


@app.post("/api/jobs/{job_id}/signoff")
def job_signoff(job_id: str, req: SignoffReq) -> dict:
    try:
        jobs.sign_off(_job(job_id), req.outcome, req.reviewer, req.note, req.acknowledged_limits)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return dict(signoff=jobs.signoff(job_id), audit=jobs.audit(job_id))


@app.delete("/api/jobs/{job_id}")
def job_delete(job_id: str) -> dict:
    jobs.delete(_job(job_id))
    return dict(deleted=job_id)


@app.get("/api/jobs/{job_id}/export.{fmt}")
def job_export(job_id: str, fmt: str) -> Response:
    _job(job_id)
    try:
        p = jobs.payload(job_id)
    except KeyError:
        raise HTTPException(409, "This proof isn't finished yet") from None
    stem = f"proof_{Path(p['names']['sample']).stem}"
    if fmt == "json":
        return JSONResponse(p, headers={"Content-Disposition": f'attachment; filename="{stem}.json"'})
    if fmt == "csv":
        return Response(findings_csv(p), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'})
    if fmt == "pdf":
        from proofer.annotate import build
        data = build(str(jobs.job_dir(job_id) / "sample.pdf"), p)
        return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{stem}_annotated.pdf"'})
    if fmt == "html":
        d = jobs.job_dir(job_id) / "pages"
        for pg in p["pages"]:
            pg["img"] = {k: "data:image/png;base64," + base64.b64encode((d / f"{pg['index']}_{k}.png").read_bytes()).decode() for k in ("ref", "sample", "overlay")}
        p["standalone"] = True
        return Response(render_standalone(p), media_type="text/html; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{stem}.html"'})
    raise HTTPException(404)


def _stamp(path: Path) -> str:
    return datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


class SettingsReq(BaseModel):
    profile: str
    overrides: dict = {}
    variable_labels: list[str] = []


@app.get("/api/settings")
def get_settings() -> dict:
    from proofer import profiles
    return dict(settings=profiles.load(), presets=profiles.presets_public(), defaults=profiles.defaults())


@app.put("/api/settings")
def put_settings(req: SettingsReq) -> dict:
    from proofer import profiles
    try:
        return dict(settings=profiles.save(req.model_dump()))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/validation")
def validation() -> dict:
    """What has actually been measured, and when. Two independent sources: the hand-written answer key
    (evaluate.py) and programmatic mutation testing on real artwork (mutate.py)."""
    out: dict = dict(answer_key=None, mutation=None)
    p = RESULTS_DIR / "details.json"
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        out["answer_key"] = dict(summary=d["summary"], measured=_stamp(p))
    m = RESULTS_DIR / "mutation.json"
    if m.exists():
        d = json.loads(m.read_text(encoding="utf-8"))
        out["mutation"] = dict(table=d["table"], total=d["total"], controls=d["controls"], per=d["per"], seed=d["seed"], measured=d.get("measured", _stamp(m)),
                               pdfs=sorted({r["src"] for r in d["rows"]}))
    return out


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
