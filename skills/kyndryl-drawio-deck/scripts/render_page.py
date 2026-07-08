#!/usr/bin/env python3
"""Crude .drawio -> PNG renderer for visual verification (colors, layout, chrome).
Usage: render_drawio.py <file.drawio> <page-name-or-index> <out.png>
"""
import re, sys, base64, io, html
from xml.etree import ElementTree as ET
from PIL import Image, ImageDraw, ImageFont

def color(c, default=None):
    if not c or c in ("none", "default"):
        return default
    m = re.match(r"light-dark\(\s*([^,]+),", c)
    if m:
        c = m.group(1).strip()
    c = c.strip()
    if re.match(r"^#[0-9a-fA-F]{6}$", c):
        return c
    return default

def style_dict(s):
    d = {}
    for part in (s or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            d[k] = v
        elif part:
            d[part] = "1"
    return d

def strip_html(v):
    v = html.unescape(v or "")
    v = re.sub(r"<br\s*/?>", "\n", v, flags=re.I)
    v = re.sub(r"</(p|div|li|ul)>", "\n", v, flags=re.I)
    v = re.sub(r"<li[^>]*>", " • ", v, flags=re.I)
    v = re.sub(r"<[^>]+>", "", v)
    return re.sub(r"\n{3,}", "\n\n", v).strip()

def load_font(size, bold=False):
    for name in ("/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""),):
        try:
            return ImageFont.truetype(name, int(size))
        except Exception:
            pass
    return ImageFont.load_default()

def main(path, page_sel, out):
    data = open(path).read()
    root = ET.fromstring(data)
    diagrams = root.findall(".//diagram")
    dia = None
    for i, d in enumerate(diagrams):
        if d.get("name") == page_sel or str(i) == page_sel:
            dia = d
            break
    if dia is None:
        print("page not found; available:", [d.get("name") for d in diagrams])
        return 1
    model = dia.find(".//mxGraphModel")
    W = int(float(model.get("pageWidth", 1600)))
    H = int(float(model.get("pageHeight", 900)))
    bg = color(model.get("background"), "#FFFFFF")
    img = Image.new("RGB", (W, H), bg)
    dr = ImageDraw.Draw(img)

    cells = {}
    for c in model.iter("mxCell"):
        cells[c.get("id")] = c

    def geom(c):
        g = c.find("mxGeometry")
        if g is None:
            return None
        return (float(g.get("x", 0)), float(g.get("y", 0)),
                float(g.get("width", 0)), float(g.get("height", 0)))

    # vertices first
    for c in model.iter("mxCell"):
        if c.get("vertex") != "1":
            continue
        st = style_dict(c.get("style"))
        g = geom(c)
        if not g:
            continue
        x, y, w, h = g
        if "image" in st.get("shape", "") or st.get("image"):
            b64 = st.get("image", "").split(",", 1)[-1]
            try:
                pic = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")
                pic = pic.resize((max(1, int(w)), max(1, int(h))))
                img.paste(pic, (int(x), int(y)), pic)
            except Exception as e:
                dr.rectangle([x, y, x + w, y + h], outline="#FF00FF")
            continue
        fill = color(st.get("fillColor"), None)
        stroke = color(st.get("strokeColor"), None)
        radius = 14 if st.get("rounded") == "1" else 0
        opacity = float(st.get("opacity", 100))
        if fill and opacity < 100:
            ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
            od = ImageDraw.Draw(ov)
            r, g_, b = tuple(int(fill[i:i+2], 16) for i in (1, 3, 5))
            od.rounded_rectangle([x, y, x + w, y + h], radius=radius,
                                 fill=(r, g_, b, int(opacity * 2.55)))
            img.paste(Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB"), (0, 0))
            dr = ImageDraw.Draw(img)
        elif fill or stroke:
            dr.rounded_rectangle([x, y, x + w, y + h], radius=radius,
                                 fill=fill, outline=stroke,
                                 width=max(1, int(float(st.get("strokeWidth", 1)))))
        txt = strip_html(c.get("value"))
        if txt:
            fs = int(float(st.get("fontSize", 12)))
            font = load_font(fs, st.get("fontStyle") == "1")
            fc = color(st.get("fontColor"), "#000000")
            align = st.get("align", "center")
            anchor_x = x + 6 if align == "left" else (x + w - 6 if align == "right" else x + w / 2)
            valign = st.get("verticalAlign", "middle")
            anchor_y = y + 4 if valign == "top" else (y + h - 4 if valign == "bottom" else y + h / 2)
            aa = {"left": "la", "right": "ra", "center": "ma"}[align]
            va = {"top": "a", "bottom": "d", "middle": "m"}[valign]
            try:
                dr.multiline_text((anchor_x, anchor_y), txt, fill=fc, font=font,
                                  anchor=aa[0] + va, align=align)
            except Exception:
                dr.multiline_text((x + 6, y + 4), txt, fill=fc, font=font)

    def edge_point(cell_id, fx, fy, fallback):
        c = cells.get(cell_id)
        if c is None:
            return fallback
        g = geom(c)
        if not g:
            return fallback
        x, y, w, h = g
        return (x + w * fx, y + h * fy)

    for c in model.iter("mxCell"):
        if c.get("edge") != "1":
            continue
        st = style_dict(c.get("style"))
        g = c.find("mxGeometry")
        sp = tp = None
        if g is not None:
            for p in g.findall("mxPoint"):
                if p.get("as") == "sourcePoint":
                    sp = (float(p.get("x", 0)), float(p.get("y", 0)))
                if p.get("as") == "targetPoint":
                    tp = (float(p.get("x", 0)), float(p.get("y", 0)))
        sp = edge_point(c.get("source"), float(st.get("exitX", 0.5)), float(st.get("exitY", 0.5)), sp) if c.get("source") else sp
        tp = edge_point(c.get("target"), float(st.get("entryX", 0.5)), float(st.get("entryY", 0.5)), tp) if c.get("target") else tp
        if not sp or not tp:
            continue
        stroke = color(st.get("strokeColor"), "#000000")
        width = max(1, int(float(st.get("strokeWidth", 1))))
        dr.line([sp, tp], fill=stroke, width=width)
        # arrowhead
        import math
        ang = math.atan2(tp[1] - sp[1], tp[0] - sp[0])
        L = 14
        for off in (0.5,):
            pts = [tp,
                   (tp[0] - L * math.cos(ang - 0.4), tp[1] - L * math.sin(ang - 0.4)),
                   (tp[0] - L * math.cos(ang + 0.4), tp[1] - L * math.sin(ang + 0.4))]
            dr.polygon(pts, fill=stroke)
        txt = strip_html(c.get("value"))
        if txt:
            fs = int(float(st.get("fontSize", 12)))
            font = load_font(fs, st.get("fontStyle") == "1")
            fc = color(st.get("fontColor"), stroke)
            mx, my = (sp[0] + tp[0]) / 2, (sp[1] + tp[1]) / 2
            bbox = dr.multiline_textbbox((mx, my), txt, font=font, anchor="mm")
            chip = color(st.get("labelBackgroundColor"))
            if chip:
                dr.rectangle([bbox[0] - 3, bbox[1] - 1, bbox[2] + 3, bbox[3] + 1], fill=chip)
            dr.multiline_text((mx, my), txt, fill=fc, font=font, anchor="mm", align="center")

    img.save(out)
    print("wrote", out, f"{W}x{H}")
    return 0

if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
