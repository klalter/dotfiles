#!/usr/bin/env python3
"""Validate a .drawio deck against the kyndryl-drawio-deck conventions.

Usage: validate_deck.py <file.drawio> [--strict]

Errors (exit 1): missing/wrong chrome (logo, page number, title), wrong logo
color for the background under it, labeled standard arrows without a white
label background, unexpected fonts.
Warnings (exit 0 unless --strict): stroke widths, endArrow deviations.
"""
import re
import sys
import hashlib

RED = "1b875671"
WHITE = "9f102191"
CORALS = ("#FE432E", "#FE462D")
ALLOWED_FONTS = {"TWK Everett Light", "TWK Everett Medium", "TWK Everett", "Monaco"}


def cells(diagram):
    """Yield (style, value, geometry-dict) per mxCell."""
    for m in re.finditer(
        r'<mxCell\b[^>]*>(?:\s*<mxGeometry.*?(?:/>|</mxGeometry>))?', diagram, re.S
    ):
        s = m.group(0)
        style = re.search(r'style="([^"]*)"', s)
        value = re.search(r'value="([^"]*)"', s)
        geo = re.search(r'<mxGeometry([^>]*)', s)
        gd = dict(re.findall(r'(\w+)="([^"]*)"', geo.group(1))) if geo else {}
        yield s, (style.group(1) if style else ""), (value.group(1) if value else ""), gd


def main(path, strict=False):
    data = open(path).read()
    try:
        from xml.etree import ElementTree as ET
        ET.fromstring(data)
    except ET.ParseError as e:
        print(f"ERROR  - file is not well-formed XML ({e}); "
              "HTML in value attributes must be entity-escaped (&lt; &gt; &quot;)")
        return 1
    data = re.sub(
        r"(image=data:image/(?:png|jpeg),)([A-Za-z0-9+/=]+)",
        lambda m: m.group(1) + "B64_" + hashlib.md5(m.group(2).encode()).hexdigest()[:8],
        data,
    )
    errors, warnings = [], []
    diagrams = re.split(r"(?=<diagram )", data)[1:]
    if not diagrams:
        print("no <diagram> pages found")
        return 1

    for d in diagrams:
        name = (re.search(r'name="([^"]*)"', d) or [None, "?"])[1]
        bg = (re.search(r'background="([^"]*)"', d) or [None, "none"])[1]
        is_cover = 'pageWidth="1900"' in d
        is_section = "#3D3C3C" in bg
        is_thankyou = "#FE432E" in bg
        is_agenda = name.lower() == "agenda"

        err = lambda m: errors.append(f"[{name}] {m}")
        warn = lambda m: warnings.append(f"[{name}] {m}")

        # detect a coral panel covering the bottom-left corner (under the logo)
        warm_left = False
        warm_left_w = 0.0
        for raw, style, value, g in cells(d):
            sl = style.lower()
            is_coral_fill = any(
                f"fillcolor=light-dark({c},{c})".lower() in sl or f"fillcolor={c}".lower() in sl
                for c in CORALS
            )
            if is_coral_fill and 'edge="1"' not in raw:
                x = float(g.get("x", 0) or 0)
                y = float(g.get("y", 0) or 0)
                w = float(g.get("width", 0) or 0)
                h = float(g.get("height", 0) or 0)
                if x <= 26 and x + w >= 150 and y + h >= 880:
                    warm_left = True
                    warm_left_w = max(warm_left_w, x + w)

        if is_cover:
            # photo covers (jpeg) need a dark scrim so white text reads
            has_photo = "image=data:image/jpeg," in d
            has_scrim = False
            for raw, style, value, g in cells(d):
                if "opacity=" in style and "fillColor=#000000" in style and 'edge="1"' not in raw:
                    if float(g.get("width", 0) or 0) >= 1800 and float(g.get("height", 0) or 0) >= 1000:
                        has_scrim = True
            if has_photo and not has_scrim:
                err("photo cover needs a full-bleed scrim overlay "
                    "(fillColor=#000000;opacity=40..70) between image and text")
            for raw, style, value, g in cells(d):
                if "fontSize=90" in style and value:
                    if float(g.get("width", 0) or 0) < 1200:
                        warn(f"cover title box w={g.get('width')} — use w=1840 so the "
                             "title cannot wrap onto the subtitle")
                # accent bar: thin coral rect near the top must be flush left
                sl = style.lower()
                if 'edge="1"' not in raw and any(f"fillcolor={c}".lower() in sl for c in CORALS):
                    h_ = float(g.get("height", 0) or 0)
                    y_ = float(g.get("y", 0) or 0)
                    x_ = float(g.get("x", 0) or 0)
                    if 0 < h_ <= 30 and y_ < 200 and x_ != 0:
                        err(f"cover accent bar starts at x={x_:g} — it must touch the "
                            "left edge of the slide (x=0, no gap)")

        logos = re.findall(r"B64_(1b875671|9f102191)", d)
        if is_cover or is_thankyou:
            pass  # cover branding handled above; thank-you page has none
        elif not logos:
            err("missing kyndryl logo (bottom-left, x=26 y=837 w=120 h=40.32)")
        else:
            want_white = warm_left or is_thankyou
            if want_white and WHITE not in logos:
                err("logo sits on coral/warm background — must be the WHITE logo")
            if not want_white and WHITE in logos and RED not in logos:
                err("logo on light/charcoal background should be the RED logo")
            for raw, style, value, g in cells(d):
                if "B64_1b875671" in style or "B64_9f102191" in style:
                    if (g.get("x"), g.get("y")) != ("26", "837"):
                        err(f"logo geometry x={g.get('x')} y={g.get('y')} (expected 26,837)")

        if not (is_cover or is_section or is_thankyou or is_agenda):
            has_pagenum = False
            has_title = False
            for raw, style, value, g in cells(d):
                if (
                    "align=right" in style
                    and "verticalAlign=bottom" in style
                    and "fontSize=18" in style
                ):
                    has_pagenum = True
                if "fontSize=36" in style and "text;" in style:
                    has_title = True
                    if warm_left and float(g.get("x", 999) or 999) < warm_left_w and "fontColor=#FFFFFF" not in style:
                        err("title over the coral panel must be white (#FFFFFF)")
            if not has_pagenum:
                err("missing page number (fontSize=18, bottom-right, color adapted to background)")
            if not has_title:
                warn("no 36px title text cell found")

        for f in set(re.findall(r"fontFamily=([^;\"&]+)", d)):
            if f not in ALLOWED_FONTS:
                err(f"unexpected fontFamily '{f}' (use TWK Everett Light/Medium or Monaco)")

        if is_agenda:
            for raw, style, value, g in cells(d):
                if "44pt" in value and float(g.get("width", 0) or 0) < 1000 \
                        and float(g.get("x", 0) or 0) > 100:
                    warn(f"agenda titles column w={g.get('width')} — use w=1400 so "
                         "44pt entries don't wrap to a second line")

        vertex_ids = set()
        vertex_geo = {}
        for raw, style, value, g in cells(d):
            if 'vertex="1"' in raw:
                m = re.search(r'id="([^"]*)"', raw)
                if m:
                    vertex_ids.add(m.group(1))
                    try:
                        vertex_geo[m.group(1)] = (
                            float(g.get("x", 0) or 0), float(g.get("y", 0) or 0),
                            float(g.get("width", 0) or 0), float(g.get("height", 0) or 0),
                        )
                    except (TypeError, ValueError):
                        pass

        for raw, style, value, g in cells(d):
            if 'edge="1"' not in raw:
                continue
            for attr in ("source", "target"):
                m = re.search(rf'{attr}="([^"]*)"', raw)
                if m and m.group(1) not in vertex_ids:
                    err(f"edge {attr}='{m.group(1)}' does not match any vertex id on the page")
            if "endArrow=none" in style:
                continue
            if "endArrow=block" not in style:
                warn("edge without endArrow=block")
            sw = re.search(r"strokeWidth=([\d.]+)", style)
            if sw and float(sw.group(1)) != 2.5:
                warn(f"edge strokeWidth={sw.group(1)} (canonical is 2.5)")
            if value:
                # label needs clear run between the two node borders
                src = re.search(r'source="([^"]*)"', raw)
                tgt = re.search(r'target="([^"]*)"', raw)
                if src and tgt and src.group(1) in vertex_geo and tgt.group(1) in vertex_geo:
                    ax, ay, aw, ah = vertex_geo[src.group(1)]
                    bx, by, bw, bh = vertex_geo[tgt.group(1)]
                    gap_x = max(bx - (ax + aw), ax - (bx + bw), 0)
                    gap_y = max(by - (ay + ah), ay - (by + bh), 0)
                    gap = max(gap_x, gap_y)
                    plain = re.sub(r"&lt;br\s*/?&gt;|&#xa;", "\n", value, flags=re.I)
                    plain = re.sub(r"&lt;[^&]*?&gt;", "", plain)  # other inline tags
                    plain = re.sub(r"&[a-z]+;|&#\w+;", " ", plain)
                    fs = re.search(r"fontSize=(\d+)", style)
                    per_char = 10 if (not fs or int(fs.group(1)) >= 17) else 7
                    label_w = max(len(x.strip()) for x in plain.split("\n")) * per_char
                    need = label_w + 60
                    if 0 < gap < label_w + 20:
                        err(f"edge label '{plain.strip()[:25]}' has only {gap:.0f}px between "
                            f"nodes (needs ~{need}px) — label will overlap a node; "
                            "spread the nodes, shorten the label, or drop it")
                    elif 0 < gap < need:
                        warn(f"edge label '{plain.strip()[:25]}' is tight: {gap:.0f}px gap "
                             f"for a ~{label_w}px label — prefer ~{need}px of run")
                sl = style.lower()
                is_standard = "strokecolor=light-dark(#3d3c3c,#3d3c3c)" in sl
                white_chip = "labelbackgroundcolor=#ffffff" in sl
                teal_small = "fontsize=14" in sl and "fontcolor=#2f7772" in sl
                if is_standard and not (white_chip or teal_small):
                    err(f"standard edge '{value[:30]}' label must be white-chip "
                        "(fontSize=18 + labelBackgroundColor=#FFFFFF) or small teal "
                        "(fontSize=14 + fontColor=#2F7772)")
                elif not is_standard and "labelbackgroundcolor" not in sl:
                    warn(f"labeled edge '{value[:30]}' has no labelBackgroundColor")
                if "fontSize" not in style:
                    warn(f"labeled edge '{value[:30]}' has no fontSize (18 standard / 14 warm)")

    for p in errors:
        print("ERROR  -", p)
    for p in warnings:
        print("warn   -", p)
    print(f"{len(diagrams)} page(s): {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors or (strict and warnings) else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--strict"]
    if len(args) != 1:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(args[0], strict="--strict" in sys.argv))
