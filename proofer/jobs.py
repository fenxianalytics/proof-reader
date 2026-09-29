"""Proof jobs: run a comparison in the background, keep everything on local disk, and record reviewer
decisions in a hash-chained, append-only audit log.

    results/jobs/<id>/
        ref.pdf  sample.pdf        the inputs, kept so the proof can be re-run and audited
        status.json                queued | running | done | error, progress
        payload.json               the report (findings, coverage, page geometry)
        pages/<n>_<kind>.png       rendered pages
        audit.jsonl                every review decision + sign-off, each entry chained to the previous one
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import __version__
from . import profiles
from .compare import compare
from .report import build_payload, page_assets, sha256

ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = ROOT / "results" / "jobs"
BATCH_DIR = ROOT / "results" / "batches"
DECISIONS = ("accepted", "rejected", "pending")
_pool = ThreadPoolExecutor(max_workers=int(os.environ.get("PROOFER_WORKERS", "2")))
_lock = threading.Lock()
TTL_HOURS = float(os.environ.get("JOB_TTL_HOURS", "0"))  # > 0 on a shared host: proofs older than this are deleted


def _purge_old() -> None:
    """Delete proofs and batches nobody has touched for JOB_TTL_HOURS. Off by default (a local install keeps everything)."""
    if TTL_HOURS <= 0:
        return
    cutoff = time.time() - TTL_HOURS * 3600
    for d in (JOBS_DIR.iterdir() if JOBS_DIR.is_dir() else []):
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
    for f in (BATCH_DIR.glob("*.json") if BATCH_DIR.is_dir() else []):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


def _write(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def _read(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def job_dir(job_id: str) -> Path:
    if not job_id.isalnum():
        raise KeyError(job_id)
    d = JOBS_DIR / job_id
    if not d.is_dir():
        raise KeyError(job_id)
    return d


def create(ref: bytes, sample: bytes, ref_name: str, sample_name: str, dpi: int = 300, ocr_on: bool = True,
           deck: bytes | None = None, deck_name: str = "", batch: str = "", key: str = "", owner: str = "") -> str:
    _purge_old()
    job_id = time.strftime("%y%m%d%H%M%S") + uuid.uuid4().hex[:4]
    d = JOBS_DIR / job_id
    (d / "pages").mkdir(parents=True)
    (d / "ref.pdf").write_bytes(ref)
    (d / "sample.pdf").write_bytes(sample)
    deck_file = ""
    if deck:
        deck_file = "deck" + (Path(deck_name).suffix.lower() or ".docx")
        (d / deck_file).write_bytes(deck)
    settings = profiles.load()
    _write(d / "status.json", dict(id=job_id, state="queued", progress=0.0, stage="Queued", settings=settings,
                                   names=dict(ref=ref_name, sample=sample_name, deck=deck_name if deck else ""), deck_file=deck_file, dpi=dpi, ocr=ocr_on,
                                   batch=batch, key=key, owner=owner,
                                   created=datetime.now().isoformat(timespec="seconds")))
    if batch:
        with _lock:
            b = _read(BATCH_DIR / f"{batch}.json")
            if b is not None:
                b["jobs"].append(dict(id=job_id, key=key or sample_name))
                _write(BATCH_DIR / f"{batch}.json", b)
    _pool.submit(_run, job_id)
    return job_id


# ── batches: many proofs submitted together, tracked as one ──────────────
def create_batch(name: str, unpaired: list[str] | None = None, owner: str = "") -> str:
    _purge_old()
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    bid = "b" + time.strftime("%y%m%d%H%M%S") + uuid.uuid4().hex[:4]
    _write(BATCH_DIR / f"{bid}.json", dict(id=bid, name=name or "Batch", created=datetime.now().isoformat(timespec="seconds"),
                                           jobs=[], unpaired=unpaired or [], owner=owner))
    return bid


def batch(bid: str) -> dict:
    if not bid.isalnum():
        raise KeyError(bid)
    b = _read(BATCH_DIR / f"{bid}.json")
    if b is None:
        raise KeyError(bid)
    rows = []
    for j in b["jobs"]:
        try:
            st = status(j["id"])
        except KeyError:
            continue
        rv = reviews(j["id"])
        so = signoff(j["id"])
        rows.append(dict(st, key=j["key"], reviewed=sum(1 for v in rv.values() if v["decision"] != "pending"),
                         signoff=so and so.get("outcome")))
    states = [r["state"] for r in rows]
    verdicts = [r.get("verdict") for r in rows if r["state"] == "done"]
    b.update(rows=rows, total=len(rows), done=states.count("done"), failed=states.count("error"),
             running=len(rows) - states.count("done") - states.count("error"),
             verdicts=dict(PASS=verdicts.count("PASS"), REVIEW=verdicts.count("REVIEW"), FAIL=verdicts.count("FAIL")),
             critical=sum((r.get("counts") or {}).get("critical", 0) for r in rows))
    return b


def batches() -> list[dict]:
    if not BATCH_DIR.is_dir():
        return []
    out = []
    for p in BATCH_DIR.glob("*.json"):
        try:
            b = batch(p.stem)
        except KeyError:
            continue
        b.pop("rows", None)
        out.append(b)
    return sorted(out, key=lambda b: b["created"], reverse=True)


def delete_batch(bid: str) -> None:
    b = batch(bid)
    for j in b["jobs"]:
        try:
            delete(j["id"])
        except KeyError:
            pass
    (BATCH_DIR / f"{bid}.json").unlink(missing_ok=True)


def _set(d: Path, **kw) -> None:
    with _lock:
        st = _read(d / "status.json", {})
        st.update(kw)
        _write(d / "status.json", st)


def _run(job_id: str) -> None:
    d = JOBS_DIR / job_id
    st = _read(d / "status.json", {})
    try:
        settings = st.get("settings") or profiles.load()
        cfg = profiles.make_config(settings, dpi=int(st.get("dpi", 300)), ocr=bool(st.get("ocr", True)))
        _set(d, state="running", stage="Reading both PDFs", progress=0.03)
        t0 = time.time()

        def progress(done: int, total: int) -> None:
            _set(d, stage=f"Comparing page {done + 1} of {total}", progress=0.05 + 0.8 * done / max(total, 1))
        deck = str(d / st["deck_file"]) if st.get("deck_file") else None

        def keep_page(pg: dict) -> dict:  # each page becomes its small screen images at once, so full-size ones are never piled up
            a = page_assets(pg)
            for kind in ("ref", "sample", "overlay"):
                (d / "pages" / f"{pg['page']}_{kind}.png").write_bytes(a[kind])
            return dict(page=pg["page"], sample_page=pg["sample_page"], assets=a)
        result = compare(str(d / "ref.pdf"), str(d / "sample.pdf"), cfg, keep_images=True, progress=progress, deck=deck, settings=settings, page_sink=keep_page)
        _set(d, stage="Rendering the report", progress=0.9)
        assets = [pg["assets"] for pg in result.pages]
        hashes = dict(ref=sha256(d / "ref.pdf"), sample=sha256(d / "sample.pdf"))
        if deck:
            hashes["deck"] = sha256(deck)
        meta = dict(job=job_id, elapsed_s=round(time.time() - t0, 1), sha256=hashes,
                    config={k: getattr(cfg, k) for k in cfg.__dataclass_fields__})
        n = st["names"]
        payload = build_payload(result, n["ref"], n["sample"], cfg, assets, lambda i, k: f"/api/jobs/{job_id}/pages/{i}/{k}.png", meta)
        payload["names"]["deck"] = n.get("deck", "")
        payload["engine"]["profile"] = profiles.PRESETS.get(settings.get("profile"), profiles.PRESETS["standard"])["label"]
        payload["id"] = job_id
        _write(d / "payload.json", payload)
        _set(d, state="done", stage="Done", progress=1.0, verdict=payload["verdict"], counts=payload["counts"],
             coverage_limited=payload["coverage_limited"], elapsed_s=meta["elapsed_s"])
    except Exception as exc:  # noqa: BLE001 - a corrupt / encrypted / unreadable PDF must become a message, not a 500
        traceback.print_exc()
        _set(d, state="error", stage="Failed", error=str(exc) or exc.__class__.__name__)


def status(job_id: str) -> dict:
    return _read(job_dir(job_id) / "status.json", {})


def payload(job_id: str) -> dict:
    d = job_dir(job_id)
    p = _read(d / "payload.json")
    if p is None:
        raise KeyError(job_id)
    p["reviews"], p["audit"], p["signoff"] = reviews(job_id), audit(job_id), signoff(job_id)
    st = status(job_id)
    p["batch"], p["key"] = st.get("batch", ""), st.get("key", "")
    return p


def listing() -> list[dict]:
    out = []
    if JOBS_DIR.is_dir():
        for d in JOBS_DIR.iterdir():
            st = _read(d / "status.json")
            if st and not st.get("batch"):  # batch proofs are listed under their batch
                rv = reviews(d.name)
                so = signoff(d.name)
                out.append({**st, "reviewed": sum(1 for v in rv.values() if v["decision"] != "pending"), "signoff": so and so.get("outcome")})
    return sorted(out, key=lambda s: s["created"], reverse=True)


def delete(job_id: str) -> None:
    shutil.rmtree(job_dir(job_id))


# ── review + sign-off, recorded in a tamper-evident log ──────────────────
def _entries(job_id: str) -> list[dict]:
    p = job_dir(job_id) / "audit.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append(job_id: str, entry: dict) -> dict:
    with _lock:
        prev = (_entries(job_id) or [{"hash": "0" * 64}])[-1]["hash"]
        entry = {**entry, "ts": datetime.now().isoformat(timespec="seconds"), "prev": prev, "engine": __version__}
        entry["hash"] = hashlib.sha256((prev + json.dumps(entry, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
        with open(job_dir(job_id) / "audit.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def audit(job_id: str) -> dict:
    """The log plus whether its hash chain still verifies (any edit or deletion breaks it)."""
    entries, prev, ok = _entries(job_id), "0" * 64, True
    for e in entries:
        body = {k: v for k, v in e.items() if k != "hash"}
        if e["prev"] != prev or e["hash"] != hashlib.sha256((prev + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode()).hexdigest():
            ok = False
        prev = e["hash"]
    return dict(entries=entries, intact=ok)


def reviews(job_id: str) -> dict:
    out: dict = {}
    for e in _entries(job_id):
        if e["type"] == "review":
            out[str(e["finding"])] = dict(decision=e["decision"], note=e.get("note", ""), reviewer=e.get("reviewer", ""), ts=e["ts"])
    return out


def signoff(job_id: str) -> dict | None:
    last = None
    for e in _entries(job_id):
        if e["type"] == "signoff":
            last = e
    return last


def review(job_id: str, finding: int, decision: str, note: str, reviewer: str) -> dict:
    if decision not in DECISIONS:
        raise ValueError("decision must be accepted, rejected or pending")
    ids = {f["id"] for f in (_read(job_dir(job_id) / "payload.json") or {}).get("findings", [])}
    if finding not in ids:
        raise ValueError(f"no finding #{finding} in this proof")
    return _append(job_id, dict(type="review", finding=finding, decision=decision, note=note.strip(), reviewer=reviewer.strip()))


def sign_off(job_id: str, outcome: str, reviewer: str, note: str, acknowledged_limits: bool) -> dict:
    """approved: every finding decided, none rejected.
    rejected: always allowed. A sign-off records who, when, and the SHA-256 of both input files."""
    if outcome not in ("approved", "rejected"):
        raise ValueError("outcome must be approved or rejected")
    if not reviewer.strip():
        raise ValueError("a reviewer name is required")
    p = _read(job_dir(job_id) / "payload.json") or {}
    if outcome == "approved":
        rv = reviews(job_id)
        real = [f for f in p["findings"] if f["severity"] != "info"]
        undecided = [f["id"] for f in real if rv.get(str(f["id"]), {}).get("decision", "pending") == "pending"]
        if undecided:
            raise ValueError(f"finding(s) {undecided} have no decision yet")
        if any(rv[str(f["id"])]["decision"] == "rejected" for f in real):
            raise ValueError("a rejected finding means the sample cannot be approved")
    return _append(job_id, dict(type="signoff", outcome=outcome, reviewer=reviewer.strip(), note=note.strip(),
                                verdict=p.get("verdict"), acknowledged_limits=acknowledged_limits, sha256=(p.get("meta") or {}).get("sha256")))
