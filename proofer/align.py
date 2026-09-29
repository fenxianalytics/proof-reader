"""Page registration: is the sample the same artwork, just placed differently?

A re-imposed file (everything shifted 1 mm), a printer scaling error (98.5 %), a slightly rotated scan or a phone
photo of the pack all move EVERY element by the same geometric transform. Compared naively that shows up as
dozens of "moved" and "restyled" findings and hides the real ones. Here the transform is estimated once, reported
once, and the sample is brought into the reference's frame before anything else is compared.

Two independent estimators:
  - live text on both sides: centres of words that occur exactly once on each page, matched by their text
  - otherwise: ORB image features on both renders, matched and filtered by RANSAC
Either way the transform must be supported by most of the page (RANSAC inliers), so one moved element or a
genuine layout edit can never be mistaken for a whole-page transform.
"""
from __future__ import annotations

import math
from collections import Counter

import cv2
import numpy as np

MM = 72 / 25.4


def _word_points(pa, pb):
    wa = [w for w in pa.get_text("words") if len(w[4]) >= 2]
    wb = [w for w in pb.get_text("words") if len(w[4]) >= 2]
    ca, cb = Counter(w[4] for w in wa), Counter(w[4] for w in wb)
    ia = {w[4]: w for w in wa if ca[w[4]] == 1}
    ib = {w[4]: w for w in wb if cb[w[4]] == 1}
    common = [t for t in ia if t in ib]
    c = lambda w: ((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
    return np.float32([c(ib[t]) for t in common]), np.float32([c(ia[t]) for t in common])


def _feature_points(img_a, img_b, dpi):
    """ORB keypoints matched between the two renders, returned in PDF points (sample -> reference)."""
    k = 150 / dpi
    ga = cv2.resize(cv2.cvtColor(img_a, cv2.COLOR_RGB2GRAY), None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    gb = cv2.resize(cv2.cvtColor(img_b, cv2.COLOR_RGB2GRAY), None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    orb = cv2.ORB_create(nfeatures=4000, fastThreshold=10)
    ka, da = orb.detectAndCompute(ga, None)
    kb, db = orb.detectAndCompute(gb, None)
    if da is None or db is None or len(ka) < 8 or len(kb) < 8:
        return np.zeros((0, 2), np.float32), np.zeros((0, 2), np.float32)
    good = []
    for m in cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(db, da, k=2):
        if len(m) == 2 and m[0].distance < 0.75 * m[1].distance:
            good.append(m[0])
    s = 72 / 150
    pb = np.float32([kb[m.queryIdx].pt for m in good]) * s
    pa = np.float32([ka[m.trainIdx].pt for m in good]) * s
    return pb, pa


def estimate(pa, pb, img_a, img_b, dpi, live: bool, move_tol_mm: float = 0.25) -> dict | None:
    """Transform taking sample page coordinates (pt) to reference page coordinates, or None when the pages are
    already registered (or no whole-page transform is supported by the evidence)."""
    src, dst = _word_points(pa, pb) if live else (np.zeros((0, 2)), np.zeros((0, 2)))
    method = "text"
    if len(src) < 8:
        src, dst = _feature_points(img_a, img_b, dpi)
        method = "features"
    if len(src) < 8:
        return None
    # already registered? most matched points sit where they did
    still = np.linalg.norm(src - dst, axis=1) < 0.6 * (1 if method == "text" else 3)
    if still.mean() >= 0.5:
        return None
    thr = 1.0 if method == "text" else 3.0
    M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=thr, maxIters=4000, confidence=0.999)
    if M is None:
        return None
    inl = inl.ravel().astype(bool)
    ratio = inl.mean()
    H, kind = np.vstack([M, [0, 0, 1]]), "similarity"
    if method == "features" and ratio < 0.6:
        # a photo or skewed scan: perspective, not just a similarity
        Hh, inh = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
        if Hh is not None and inh.mean() > ratio:
            H, inl, kind = Hh, inh.ravel().astype(bool), "perspective"
            ratio = inl.mean()
    if inl.sum() < 8 or ratio < 0.5:
        return None
    a, b = H[0, 0], H[1, 0]
    scale = math.hypot(a, b) if kind == "similarity" else float(np.sqrt(abs(np.linalg.det(H[:2, :2]))))
    rot = math.degrees(math.atan2(b, a))
    w, h = pa.rect.width, pa.rect.height
    corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
    moved = cv2.perspectiveTransform(corners, H).reshape(-1, 2) - corners.reshape(-1, 2)
    # translation that the transform applies at the page centre, as a person would describe the shift
    ctr = cv2.perspectiveTransform(np.float32([[[w / 2, h / 2]]]), H).reshape(2) - np.float32([w / 2, h / 2])
    if np.abs(moved).max() < move_tol_mm * MM:
        return None
    resid = np.linalg.norm(cv2.perspectiveTransform(src[inl].reshape(-1, 1, 2), H).reshape(-1, 2) - dst[inl], axis=1)
    return dict(H=H, kind=kind, method=method, scale=float(scale), rotation=float(rot),
                dx_mm=float(-ctr[0] / MM), dy_mm=float(-ctr[1] / MM), max_corner_mm=float(np.abs(moved).max() / MM),
                inliers=int(inl.sum()), matches=int(len(src)), ratio=float(ratio), residual_pt=float(np.median(resid)))


def describe(T: dict) -> tuple[str, str]:
    """(message, severity) for the one finding that reports the whole-page transform."""
    parts = []
    sc, rot = 1 / T["scale"], -T["rotation"]  # T maps sample -> reference; describe the sample as printed
    if abs(sc - 1) > 0.002:
        parts.append(f"scaled to {sc * 100:.1f}%")
    if abs(rot) > 0.1:
        parts.append(f"rotated {rot:+.1f}°")
    if math.hypot(T["dx_mm"], T["dy_mm"]) > 0.2:
        parts.append(f"shifted {T['dx_mm']:+.1f} mm x, {T['dy_mm']:+.1f} mm y")
    if T["kind"] == "perspective":
        parts.append("with perspective distortion (looks like a photo or a skewed scan)")
    msg = "Whole page " + (", ".join(parts) or "re-positioned") + " relative to the reference. The sample was aligned before comparing, so the findings below are real content changes."
    sev = "major" if (abs(T["scale"] - 1) > 0.002 or abs(T["rotation"]) > 0.5 or math.hypot(T["dx_mm"], T["dy_mm"]) >= 1.0) else "minor"
    if T["kind"] == "perspective":
        sev = "info"
    return msg, sev


def map_rect(H, r):
    if not r:
        return r
    x0, y0, x1, y1 = r
    pts = cv2.perspectiveTransform(np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]).reshape(-1, 1, 2), H).reshape(-1, 2)
    return [float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())]


def warp(img_b, H, shape_a, dpi, border=255):
    """Sample render resampled into the reference page's pixel frame (border = paper: 255 in RGB, 0 in CMYK)."""
    k = dpi / 72
    K = np.diag([k, k, 1.0])
    Hp = K @ H @ np.linalg.inv(K)
    return cv2.warpPerspective(img_b, Hp, (shape_a[1], shape_a[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                               borderValue=(border,) * img_b.shape[2])


def render_aligned(page, H, shape_a, dpi, colorspace=None, border=255):
    """Re-render the sample PDF page straight into the reference's pixel frame (affine transforms only). Unlike
    warping an already-rendered picture, vectors and text stay crisp - only one resampling, done by the PDF renderer."""
    import pymupdf
    k = dpi / 72
    m = pymupdf.Matrix(H[0, 0], H[1, 0], H[0, 1], H[1, 1], H[0, 2], H[1, 2]) * pymupdf.Matrix(k, k)
    iso = pymupdf.open()  # render an isolated copy: rendering with a matrix must not disturb the page later text reads use
    iso.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
    pix = iso[0].get_pixmap(matrix=m, alpha=False, colorspace=colorspace or pymupdf.csRGB)
    src = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)
    out = np.full((shape_a[0], shape_a[1], pix.n), border, np.uint8)
    x0, y0 = pix.x, pix.y
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    w = min(pix.w - sx0, shape_a[1] - dx0)
    h = min(pix.h - sy0, shape_a[0] - dy0)
    if w > 0 and h > 0:
        out[dy0:dy0 + h, dx0:dx0 + w] = src[sy0:sy0 + h, sx0:sx0 + w]
    return out


def flatfield(ref: np.ndarray, smp: np.ndarray, sigma: float = 40) -> np.ndarray:
    """Remove the slow lighting gradient of a photo: match the sample's local brightness to the reference's."""
    a, b = ref.astype(np.float32), smp.astype(np.float32)
    ba, bb = cv2.GaussianBlur(a, (0, 0), sigma), cv2.GaussianBlur(b, (0, 0), sigma)
    return np.clip(b * (ba + 1) / (bb + 1), 0, 255).astype(np.uint8)
