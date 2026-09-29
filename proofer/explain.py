"""Plain-language justification for a finding: the number that was actually measured and the
threshold that made it fire, pulled from Finding.detail and Config rather than restating the message."""
from __future__ import annotations

from .compare import Config, Finding


def explain(f: Finding, cfg: Config) -> str:
    d = f.detail
    key = (f.category, f.kind)

    if key == ("text", "removed"):
        return (f"No block in the sample matched this text closely enough (SequenceMatcher ratio stayed below "
                 f"cfg.min_text_match = {cfg.min_text_match:.2f}), so it's scored as deleted rather than reworded.")
    if key == ("text", "added"):
        return (f"No block in the reference matched this text closely enough (ratio below "
                 f"cfg.min_text_match = {cfg.min_text_match:.2f}), so it's scored as new rather than reworded.")
    if key == ("text", "changed"):
        return (f"The paragraphs containing this text were matched to each other first (ratio ≥ "
                 f"cfg.min_text_match = {cfg.min_text_match:.2f}), then diffed word-by-word; this word range is where "
                 f"they differ.")
    if key == ("format", "text_style"):
        before = ", ".join(f"{s}pt {fn}" for s, fn in d.get("before", [])) or "?"
        after = ", ".join(f"{s}pt {fn}" for s, fn in d.get("after", [])) or "?"
        return f"Wording is identical; only font/size changed on this block: {before} → {after}."
    if key == ("barcode", "digits_mismatch"):
        return (f"The bars decode to \"{d.get('encoded')}\" but the human-readable digits printed beside them read "
                 f"\"{d.get('printed')}\" — read independently from the text layer, not from the barcode.")
    if key == ("barcode", "invalid_checksum"):
        return "The barcode's own check digit fails to validate against its payload — most scanners will reject it outright, independent of anything else changing."
    if key == ("barcode", "payload_changed"):
        return "No barcode in the reference decodes to this value within 30 mm of it, so it's scored as the payload changing rather than a move."
    if key == ("barcode", "orientation"):
        return f"Rotation changed by {d.get('rotation', 0):+.1f}°, past the ±{cfg.angle_tol}° tolerance (cfg.angle_tol)."
    if key == ("barcode", "shifted"):
        mm = d.get("mm", 0)
        return (f"Centre moved {mm:.2f} mm, past the {cfg.barcode_shift_mm} mm tolerance (cfg.barcode_shift_mm), "
                 f"while length stayed within ±{cfg.barcode_scale_tol:.0%} of the reference — scored as a shift, not a resize.")
    if key == ("barcode", "scaled"):
        ratio = d.get("ratio", 1.0)
        return (f"Bar length ratio is {ratio:.3f} sample:reference ({abs(ratio - 1) * 100:.0f}% "
                 f"{'smaller' if ratio < 1 else 'larger'}), past the ±{cfg.barcode_scale_tol:.0%} tolerance (cfg.barcode_scale_tol).")
    if key == ("barcode", "missing"):
        return "No barcode in the sample decodes to this value, and none sits within 30 mm of its reference position."
    if key == ("barcode", "added"):
        return "This barcode's value doesn't appear anywhere in the reference render."
    if key == ("barcode", "low_contrast"):
        c = d.get("contrast", 0.0)
        return (f"The lightest and darkest tones within the barcode's own footprint differ by only {c:.0%} of the "
                 f"full 0-255 range (2nd-98th percentile) — below the {cfg.barcode_min_contrast:.0%} threshold "
                 f"(cfg.barcode_min_contrast). Not a full ISO/IEC 15416 grade, but a practical signal that bars and "
                 f"background are too close in tone to scan reliably.")
    if key == ("barcode", "low_reflectance"):
        r = d.get("max_reflectance", 0.0)
        return f"Even the lightest tone in the barcode's footprint is only {r:.0%} reflectance — below cfg.barcode_min_reflectance ({cfg.barcode_min_reflectance:.0%}); the background itself is too dark for a scanner's usual sensitivity range."
    if key == ("barcode", "quiet_zone_violation"):
        return f"More than 10% of the {cfg.barcode_quiet_zone_mm:.0f} mm margin immediately beside the bars isn't blank paper — a scanner's quiet-zone requirement, checked directly against the rendered pixels there."
    if key == ("layout", "moved") and "match" not in d:
        return ("The same words disappear from one place and reappear, word for word, somewhere else on the page, so this is "
                f"reported as one move ({d.get('mm', 0):.1f} mm) rather than a deletion plus an addition.")
    if key == ("structure", "page_transform"):
        how = "unique words matched between the two text layers" if d.get("method") == "text" else "image features matched between the two renders"
        return (f"{d.get('inliers', 0)} of {d.get('matches', 0)} {how} agree on one whole-page transform (median error {d.get('residual_pt', 0):.2f} pt). "
                "A single moved element can't produce that, so the page was aligned before every other check and this is reported once.")
    if key[0] == "color" and key[1] in ("spot_replaced", "spot_added", "spot_removed"):
        return (f"Named spot colours read from the PDF's colour spaces: reference {', '.join(d.get('spots_a', [])) or 'none'}; "
                f"sample {', '.join(d.get('spots_b', [])) or 'none'}. A spot colour is its own ink and plate on press.")
    if key == ("color", "overprint_changed"):
        return "Overprint flags (/OP, /op) in the page's graphics states differ. A screen render ignores overprint; a press does not."
    if key == ("structure", "page_order"):
        return "Pages were paired by content similarity; the best pairing isn't page-for-page, so the pages were compared in the order shown."
    if key == ("color", "separation_changed"):
        extra = " The ink shape is identical but it is now built from different inks - invisible on screen, different on press." if d.get("rich_black") else ""
        return (f"Both pages were rendered to CMYK and each ink plate compared on its own; plate(s) {', '.join(d.get('plates', []))} changed by more than "
                f"{cfg.separation_tol:.0f}% where the artwork's shape is unchanged.{extra}")
    if key == ("layout", "moved"):
        n, match = d.get("elements", 1), d.get("match")
        what = "This element" if n == 1 else f"This block of {n} elements"
        match_txt = f"{match:.0%}" if match is not None else "?"
        return (f"{what} template-matched at {match_txt} confidence at its new position (≥90% required to call it a "
                 f"move), displaced ({d.get('dx_mm', 0):+.1f}, {d.get('dy_mm', 0):+.1f}) mm — past the "
                 f"{cfg.move_tol_mm} mm tolerance (cfg.move_tol_mm).")
    if key == ("color", "color_shift"):
        de = d.get("delta_e", 0.0)
        return (f"Edge shapes overlap ≥90% (same artwork, not a different element), but colour changed by ΔE {de:.1f} "
                 f"(CIE76) — past the {cfg.delta_e} ΔE change threshold (cfg.delta_e); {de:.1f} ≥ 10 is rated major, "
                 f"below that minor.")
    if key == ("color", "colorant_changed"):
        de = d.get("delta_e", 0.0)
        return (f"The PDF's own {d.get('channel', 'fill')} colour value for this shape differs between reference and "
                 f"sample by ΔE {de:.1f} — read directly from the drawing command, not sampled from rendered pixels, "
                 f"so this catches changes antialiasing could otherwise mask.")
    if key == ("braille", "text_changed"):
        return f'Braille dots were detected and decoded independently on each side: "{d.get("decoded_a")}" vs "{d.get("decoded_b")}" — a semantic mismatch, not just a pixel difference.'
    if key == ("braille", "removed"):
        return "A cluster of braille dots in the reference has no matching dot cluster within 20pt of it in the sample."
    if key == ("braille", "added"):
        return "A cluster of braille dots in the sample has no matching dot cluster in the reference."
    if key == ("layer", "removed"):
        return "This optional-content-group (layer) name exists in the reference PDF's layer definitions but not the sample's — read from the PDF structure, independent of anything being visibly different when rendered."
    if key == ("layer", "added"):
        return "This layer name exists in the sample PDF's structure but not the reference's."
    if key == ("layer", "visibility_changed"):
        return f"This layer's default on/off state changed: {d.get('before')} → {d.get('after')} — read from the PDF's layer configuration, not inferred from rendering."
    if key == ("graphic", "removed"):
        return "Ink pixel count in the sample region is ≤10% of the reference's here — treated as the element being deleted rather than merely faded or recoloured."
    if key == ("graphic", "added"):
        return "Ink pixel count in the reference region is ≤10% of the sample's here — treated as a new element rather than a recolour."
    if key == ("graphic", "changed"):
        area = d.get("area_mm2", 0.0)
        ocr_note = (f" OCR read \"{d.get('ocr_a', '')}\" (reference) vs \"{d.get('ocr_b', '')}\" (sample) in this region; a differing digit or unit makes it critical, any other differing wording at least major." if "ocr_a" in d else "")
        return ocr_note + (f"Neither the edge-shape check (recolour) nor the ink-ratio check (add/remove) matched, so this is a "
                 f"general visual change over {area:.1f} mm² (rated minor below 2.0 mm², major at or above).")
    if key == ("structure", "page_count"):
        return "Reference and sample have a different number of pages; only the pages both files have were compared."
    if key == ("structure", "page_size"):
        return f"Page dimensions differ by more than the {cfg.size_tol_pt} pt tolerance (cfg.size_tol_pt); the visual check on this page also fell back to the looser image-only tolerance because the size mismatch alone would otherwise look like resampling noise."
    if key == ("info", "no_text_layer"):
        return "At least one file has no extractable text layer (flattened/outlined artwork), so word-level text comparison was skipped for this page in favour of a looser pixel comparison."
    if key == ("structure", "page_removed"):
        return "Pages were paired by content similarity (not just by position), and nothing in the sample resembled this reference page closely enough (cfg.page_align_min_sim)."
    if key == ("structure", "page_added"):
        return "Pages were paired by content similarity (not just by position), and nothing in the reference resembled this sample page closely enough (cfg.page_align_min_sim)."
    if key == ("structure", "page_box"):
        return "Trim / bleed / media box geometry is read from the PDF page dictionary. It defines where the die cuts and how much bleed the printer gets, and is invisible in a rendered picture."
    if key == ("structure", "page_rotation"):
        return "The /Rotate entry of the page differs, so viewers and RIPs will present the artwork turned relative to the reference."
    if key == ("structure", "font_not_embedded"):
        return "These fonts appear in the sample's font list without an embedded font program; whoever opens or prints the file substitutes their own, which can reflow or change glyphs."
    if key == ("structure", "image_resolution"):
        return (f"Effective resolution = image pixels / placed width in inches. Reference {d.get('ppi_a', 0):.0f} ppi vs sample {d.get('ppi_b', 0):.0f} ppi; "
                f"flagged when the sample falls below {cfg.image_ppi_drop:.0%} of the reference and under 300 ppi (major under 150 ppi).")
    if key == ("copydeck", "text_changed"):
        return ("The approved paragraph was located on the artwork wherever it sits (order, panels and line breaks don't matter), "
                "then compared word by word" + (" - character by character on image-only artwork, read by OCR, where spacing is ignored." if f.confidence == "medium" else ".")
                + " Digits and units make it critical.")
    if key == ("copydeck", "missing"):
        return f"No place on the artwork matches this approved paragraph closely enough (best match {d.get('best_score', 0):.0%}, 50% needed to count as the same paragraph with edits)."
    if key == ("copydeck", "not_in_deck"):
        return "This artwork text isn't accounted for by any approved paragraph, including repeats of approved text on other panels. Barcode captions are left to the barcode check."
    if key == ("spelling", "unknown_word"):
        return ("Not found in the English, French, German, Spanish, Italian, Portuguese or Dutch dictionaries, the product dictionary "
                "(dictionary.txt), the reference artwork or the approved text. Add product names to dictionary.txt to accept them.")
    if key == ("barcode", "caption_changed"):
        return "The text printed beside the bars was read by OCR on both files and differs; the bars themselves decode identically."
    if key == ("barcode", "unverified"):
        return "A printed barcode number has no decodable symbol beside it."
    return f"{f.category}/{f.kind}: no specific explanation template yet — see the message and detail fields."
