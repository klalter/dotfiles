---
name: kyndryl-drawio-deck
description: Create PPT-like draw.io (.drawio) slide decks in the Kyndryl storyboard style — cover, agenda, section dividers, content slides with flow diagrams, warm-head slides, thank-you page. Use when asked to build a presentation/storyboard/deck as a draw.io file, or to restyle a drawio to match the Kyndryl policy-storyboard look (TWK Everett fonts, teal/coral palette, kyndryl logo, page numbers).
---

# Kyndryl draw.io deck

Build multi-page `.drawio` files that look like PowerPoint slides, matching the
reference deck exactly: `references/policy-full-storyboard.drawio` (39 pages).
When in doubt about any visual detail, open the reference and copy the style
string of the equivalent element — do not invent styles.

## File skeleton

```xml
<mxfile host="app.diagrams.net" pages="N">
  <diagram id="unique-id" name="Cover"> <mxGraphModel ...> <root>
    <mxCell id="0"/> <mxCell id="1" parent="0"/>
    ... cells parent="1" ...
  </root> </mxGraphModel> </diagram>
  ... one <diagram> per slide ...
</mxfile>
```

**Escaping rule (easy to get wrong):** every `value="..."` is XML attribute
text — any HTML inside it (`<b>`, `<br>`, `<span>`, `<font>`, `<ul>`, `<li>`,
`<p>`) must be entity-escaped (`&lt;` `&gt;` `&quot;`), never literal `< >`.
A single raw angle bracket makes the whole file unopenable in draw.io. The
examples below show the escaped form; generate values through a helper that
escapes for you.

Page setup (`mxGraphModel` attrs):
- Cover page: `pageWidth="1900" pageHeight="1070" background="#000000"`
- All other pages: `pageWidth="1600" pageHeight="900"`, plus `grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" math="0" shadow="0"`
- Page backgrounds used: `none` (white), mint `light-dark(#E4F4F1,#E4F4F1)`,
  warm paper `#F2F1ED` / `light-dark(#F2F1ED,#F2F1ED)`, section charcoal
  `light-dark(#3D3C3C,#3D3C3C)`, thank-you coral `light-dark(#FE432E,#FE432E)`.
  (Rare variants also present: plain `#ffffff`, and one asymmetric
  `light-dark(#E4F4F1,#FFFFFF)` — prefer the canonical five.)

Diagram naming: `name="Cover"`, `name="Agenda"`, dividers are `name="NN-Section"`
(01-Section, 02-Section, …), content pages share one running two-digit counter
(`02`, `03`, …) that section/agenda/cover pages do NOT consume, and the
thank-you page is `name="99"`. The big digit displayed on a divider ("01") is
the section index, independent of the content-page counter.

## Fonts (exact names, always with fontSource)

- Body/everything: `fontFamily=TWK Everett Light;fontSource=https%3A%2F%2Ffonts.googleapis.com%2Fcss%3Ffamily%3DTWK%2BEverett%2BLight;`
- Display (cover title, section number+title, agenda entries): `fontFamily=TWK Everett Medium;fontSource=https%3A%2F%2Ffonts.googleapis.com%2Fcss%3Ffamily%3DTWK%2BEverett%2BMedium;` — often with inner HTML spans forcing `font-family: "TWK Everett Light"` at large size.
- Code: `fontFamily=Monaco;` 12–14px, `fontColor=#D4D4D4` on a dark panel
  (`fillColor=#070707` or `#111111`), VS Code syntax colors in inner HTML:
  default text `#D4D4D4`, keywords `#569CD6`, identifiers `#9CDCFE`, strings
  `#CE9178`, comments `#6A9955`, function names `#DCDCAA`, numbers `#B5CEA8`.

## Color palette

| Role | Value |
|---|---|
| Teal heading | `#3D6E78` |
| Teal accent text / arrow labels on warm panel | `#2F7772` |
| Body text | `#242321` |
| Muted text (bands, side notes) | `#565049` |
| Page number gray | `#BFBFBF` |
| Node fill (standard) | `light-dark(#f2f1ed, #26241f)` |
| Node stroke (standard) | `#9B978D` |
| Emphasis node fill | `light-dark(#3D3C3C,#EDEDED)` |
| Alert/coral node fill | `light-dark(#FE462D,#FE462D)` |
| Warm-head panel / thank-you bg | `#FE432E` |
| Band fill | `#F2F1EE` |
| Mint bg / dashed frames & arrows on warm panel | `#E4F4F1` |
| Arrow stroke | `light-dark(#3D3C3C,#3D3C3C)` |

## Standard chrome — EVERY 1600×900 page gets all three

1. **Title** (skip on section/thank-you pages, they have their own):
```
style="text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;whiteSpace=wrap;rounded=0;fontFamily=TWK Everett Light;fontSource=https%3A%2F%2Ffonts.googleapis.com%2Fcss%3Ffamily%3DTWK%2BEverett%2BLight;fontSize=36;fontColor=#3D6E78;fontStyle=1;"
geometry: x=26 y=22 w=1020 h=70
```
On dark/warm pages the title fontColor is `#FFFFFF` instead of `#3D6E78`.
Watch for inner-span overrides when copying from the reference: some cells
(Agenda heading, photo-panel pages) carry an outer
`fontColor=light-dark(#242321,#3D6E78)` that is NOT what renders — an inner
`<font style="color: light-dark(rgb(61,110,120), …)">` span forces teal. If
you copy only the outer style string you get the wrong color; prefer setting
the color you want directly in the outer style with no conflicting span.

2. **Page number** — two digits ("03"), bottom-right:
```
style="text;html=1;strokeColor=none;fillColor=none;align=right;verticalAlign=bottom;whiteSpace=wrap;rounded=0;fontFamily=TWK Everett Light;fontSource=...TWK%2BEverett%2BLight;fontSize=18;fontColor=#BFBFBF;fontStyle=1;"
geometry: x=1534 y=837 w=60 h=40
```
Page-number color adapts to what's behind it: `#BFBFBF` on white,
`light-dark(#696969,#FFFFFF)` on warm paper `#F2F1ED`, `#FFFFFF` on dark,
`light-dark(#E4F4F1,#E4F4F1)` when the bottom-right sits on a coral panel.

3. **Logo** — bottom-left, exact geometry `x=26 y=837 w=120 h=40.32`:
```
style="shape=image;verticalLabelPosition=bottom;labelBackgroundColor=default;verticalAlign=top;aspect=fixed;imageAspect=0;image=data:image/png,<BASE64>;rounded=1;movable=0;resizable=0;rotatable=0;deletable=0;editable=0;locked=1;connectable=0;"
```
**Logo color rule — the logo must contrast with whatever is behind it:**
- Light background under the logo → **red logo**: inline `assets/logo-red.b64`.
- Warm-head coral panel (`#FE432E` or `#FE462D`) covering the bottom-left →
  **white logo**: inline `assets/logo-white.b64` (also drop `aspect=fixed` to
  match ref). If the coral panel is on the RIGHT half, the logo still sits on
  the light half → red logo.
- Charcoal section pages use the red logo (it reads fine on `#3D3C3C`).
- The cover and the thank-you page carry no separate logo cell.

## Page templates

### Cover (1900×1070, bg #000000)

Pick a DIFFERENT cover image for every new deck — rotate through
`assets/covers/`: `dark-wave.b64` (PNG, the original art — kyndryl logo and
"The Heart of Progress" are baked into the image), `forest.b64`, `globe.b64`,
`waves.b64` (JPEGs — inline as `image=data:image/jpeg,<contents>`).

Layer order (bottom → top):
1. **Image cell** — full-bleed, x=0 y=0 w=1900 h=1070, locked
   (`movable=0;...;locked=1;`).
2. **Scrim overlay** (photo covers only, so white text always reads — see the
   look in the brand samples): full-bleed locked rect
   `rounded=0;fillColor=#000000;strokeColor=none;opacity=70;`. Use opacity=70
   by default; on an already-dark photo (forest, waves) drop toward 40 so the
   page doesn't go pitch black. `dark-wave` needs no scrim.
3. **Accent bar** top-left: `fillColor=#FE462D;strokeColor=none;` **x=0** y=95
   w=470 h=10. The bar MUST touch the left edge of the slide — x=0, no gap
   between the rectangle and the page edge (see the brand cover samples).
4. **Title**: TWK Everett Medium, `fontSize=90`,
   `fontColor=light-dark(#FFFFFF,#FFFFFF)`, x=30 y=430 **w=1840** h=110. The
   full-width box is deliberate: at 90px a title wraps after ~15 characters
   in a narrow box and lands on the subtitle. If the title still wraps to 2
   lines (~35+ chars), grow h to 220 and push everything below down by 110.
5. **Subtitle**: `fontSize=26`, white span in HTML, x=30 y=620 w=1500 —
   never closer than ~80px below the title box bottom.
6. **Presenter / team** (optional): `fontSize=20`, white, x=30 y=880.
7. **Date**: `fontSize=20`, inner span TWK Everett Light white, x=30 y=1000.
8. **Branding** (photo covers only — dark-wave has it baked in): white logo
   `assets/logo-white.b64` at x=1560 y=830 w=280 h=94, and below it the
   tagline `fontSize=32`, right-aligned at x=1360 y=940 w=480:
   `value="The Heart of &lt;font color=&quot;#FE462D&quot;&gt;Pro&lt;/font&gt;gress"`
   in white TWK Everett.

### Agenda (bg varies — pick from the palette)
- Background rotates between decks: mint `light-dark(#E4F4F1,#E4F4F1)`, warm
  paper `#F2F1ED`, white `none`, or charcoal `light-dark(#3D3C3C,#3D3C3C)`.
  On light backgrounds the text is teal `light-dark(#3D6E78,#3D6E78)`; on
  charcoal use white `light-dark(#FFFFFF,#3D6E78)` and the red logo still
  works.
- Heading "Agenda": fontSize=26 base, TWK Everett Medium, inner font color
  `#3D6E78` (white on charcoal), x=26 y=22.
- Numbers column (01/02/03…) x=31 y=159 w=85 and titles column x=146 y=159
  **w=1400** (the reference's 842.5 wraps any 44pt title over ~25 characters
  onto a second line — use the full width so each entry stays on one line):
  inner spans `font-size: 44pt; font-family: "TWK Everett Light"`, entries
  separated by `<br><br>`.
- Red logo bottom-left. No page number on the reference agenda.

### Section divider (bg `light-dark(#3D3C3C,#3D3C3C)`)
- Number cell ("01"): x=26 y=22 w=85 h=89, `fontSize=80`,
  `fontColor=light-dark(#FFFFFF,#3D6E78)`, `fontStyle=1`, TWK Everett Medium
  with inner span `font-family: "TWK Everett Light"`.
- Title cell: same style, x=173 y=22 w=842.5 h=114.
- Red logo bottom-left. No page number.

### Content slide (bg none / mint / #F2F1ED)
Title + page number + red logo, then diagram content (see building blocks).
Optional left bullets column:
```
style="text;strokeColor=none;fillColor=none;align=left;verticalAlign=top;rounded=1;fontSize=24;fontColor=#242321;fontFamily=TWK Everett Light;fontSource=https://fonts.googleapis.com/css?family=TWK+Everett+Light;html=1;whiteSpace=wrap;"
value="&lt;ul&gt;&lt;li&gt;point&lt;/li&gt;&lt;/ul&gt;..."  x≈52 y≈202 w≈376
```

### Warm-head content slide (bg none + coral panel)
- First cell: full-height locked panel `rounded=0;whiteSpace=wrap;html=1;fillColor=light-dark(#FE432E,#FE432E);fontColor=light-dark(#FFFFFF,#FE432E);strokeColor=none;movable=0;resizable=0;rotatable=0;deletable=0;editable=0;locked=1;connectable=0;` w=800 h=900 x=0 y=0.
  Width varies in the reference (800 on page 09, 400 on page 26, and page 10
  puts an 800-wide panel on the RIGHT at x=800); h=900 always.
- Title in **white** when it sits on the panel. **White logo** bottom-left when
  the panel covers the bottom-left corner.
- Optional grouping frame on the panel — two reference forms: dashed
  `fillColor=none;dashed=1;dashPattern=8 8;strokeColor=light-dark(#E4F4F1,#E4F4F1);`
  (page 09) or solid `rounded=1;arcSize=8;fillColor=none;strokeColor=light-dark(#E4F4F1,#E4F4F1);strokeWidth=1.6;` (page 10).
- Arrows that live on the panel: `strokeColor=light-dark(#E4F4F1,#E4F4F1)`,
  label `fontSize=14;fontStyle=1;fontColor=#2F7772;labelBackgroundColor=default`.
- Page number over a coral bottom-right: mint `light-dark(#E4F4F1,#E4F4F1)`
  (warm-head coral) or plain `#FFFFFF` (alert coral `#FE462D`).

### Thank-you (bg `light-dark(#FE432E,#FE432E)`)
- Two stacked locked white panels right side: `assets/panel-white.b64`,
  w=410 h=450, x=1190 y=0 and y=450.
- "Thank you": `fontFamily=TWK Everett;fontSize=101;fontColor=#FFFFFF;fontStyle=1;` x=19 y=484.

## Building blocks (content diagrams)

**Standard node** (~250×100):
```
style="rounded=1;whiteSpace=wrap;html=1;arcSize=12;align=center;verticalAlign=middle;fillColor=light-dark(#f2f1ed, #26241f);strokeColor=#9B978D;fontFamily=TWK Everett Light;fontSource=...TWK%2BEverett%2BLight;fontSize=21;fontColor=#242321;fontStyle=1;"
value="&lt;b&gt;Title&lt;/b&gt;&lt;br&gt;&lt;font style=&quot;font-size: 15px&quot;&gt;subtitle&lt;/font&gt;"
```

**Emphasis node** (dark): same but `fillColor=light-dark(#3D3C3C,#EDEDED);strokeWidth=2;fontColor=#FFFFFF;dashed=1;strokeColor=none;`

**Alert node** (coral): same but `fillColor=light-dark(#FE462D,#FE462D);strokeWidth=2;fontColor=#FFFFFF;dashed=1;strokeColor=none;`

**Band** (full-width takeaway strip, bottom of slide ~y=731 h=55–71):
```
style="rounded=1;whiteSpace=wrap;html=1;arcSize=8;align=center;verticalAlign=middle;spacing=8;fillColor=#F2F1EE;strokeColor=#F2F1EE;strokeWidth=1.6;fontFamily=TWK Everett Light;fontSource=...;fontSize=20;fontColor=#565049;fontStyle=1;"
value="&lt;b&gt;short takeaway sentence&lt;/b&gt;"
```
Careful: band fill is `#F2F1EE`, warm-paper page background is `#F2F1ED` —
one hex digit apart, both intentional; don't "correct" one into the other.

**Side note text**: `fontSize=22;fontColor=#565049;fontStyle=0;` align left.

## Arrows — copy these details exactly

The line itself is always the same on flow pages: `endArrow=block;rounded=0;strokeWidth=2.5;strokeColor=light-dark(#3D3C3C,#3D3C3C);startArrow=none;startFill=0;html=1;` — and always wire `source`/`target` to cell
ids AND set `exitX/exitY`/`entryX/entryY` anchors, keeping fallback
`<mxPoint as="sourcePoint"/>`/`targetPoint` in the geometry.

Two legitimate **label** styles exist on that standard stroke:

1. **White-chip label** (the default for new decks — use this):
```
style="endArrow=block;rounded=0;strokeWidth=2.5;strokeColor=light-dark(#3D3C3C,#3D3C3C);fontColor=light-dark(#3D3C3C,#3D3C3C);exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;align=center;verticalAlign=middle;startArrow=none;startFill=0;html=1;fontSize=18;fontFamily=TWK Everett Light;fontSource=...TWK%2BEverett%2BLight;labelBackgroundColor=#FFFFFF;"
```
   Label font **18px** TWK Everett Light, fontColor matches the stroke, and
   **`labelBackgroundColor=#FFFFFF`** puts the label on a white chip over the
   line.
2. **Small teal label** (the reference's most frequent variant, good for dense
   diagrams where chips would overlap): `fontSize=14;fontColor=#2F7772;fontStyle=1;labelBackgroundColor=default;`
   on the same 2.5px stroke.

Pick one per page — don't mix chip and no-chip labels in the same diagram.

**Label spacing:** a labeled arrow needs clear run between the two node
borders or the label collides with a node. Budget roughly 10px per character
at 18px (7px at 14px) plus 60px of breathing room on each side — e.g. the
label "returns" (7 chars ≈ 70px) needs nodes at least ~190px apart. If the
layout can't give the edge that much run, either shorten the label, move the
label along the edge with the geometry offset (`<mxGeometry relative="1"
x="-0.3">` shifts it toward the source), or drop the label. Never let a chip
touch or overlap the node it points at.

- On the warm coral panel: stroke `light-dark(#E4F4F1,#E4F4F1)`, label 14px
  bold `#2F7772`, `labelBackgroundColor=default`.
- Sequence/swimlane pages (reference pages 19 and 22) use a thin variant:
  `strokeWidth=1;strokeColor=light-dark(#000000,#000000);fontSize=16` with no
  label chip — only for sequence diagrams between vertical lifelines. (Pages
  25 and 29 each drift into their own hybrids; don't copy those.)

## Make each deck look distinct

The reference deck itself mixes layouts and colors page to page — new decks
must do the same, and must not repeat the previous deck's combination:

- **Cover image**: rotate through `assets/covers/` (dark-wave, forest, globe,
  waves) — never default to the same one twice in a row.
- **Flow direction**: alternate horizontal (left→right, like reference page
  03) and vertical (top→down, like the warm-head mini-flows) layouts across
  content pages; grids (2×3 node walls) are a third option.
- **Warm panel side**: left (pages 09/26) or right (page 10), and width 400
  or 800.
- **Accent fills**: besides the charcoal emphasis node, the reference also
  uses teal `light-dark(#2e7772, #ededed)` (white text), dark blue `#082a49`,
  and deep green `#042315`/`#14532d` as occasional accent node fills — vary
  which accent a deck leans on.
- **Page backgrounds**: distribute the five backgrounds (white/none, mint,
  warm paper, charcoal sections, coral) differently from deck to deck; the
  agenda background rotates too (see Agenda).
- **Band position** can sit bottom-left, bottom-center, or bottom-right.

## Assets

`assets/*.b64` hold raw base64 (no data-uri prefix). Inline PNGs as
`image=data:image/png,<contents>` and JPEGs as
`image=data:image/jpeg,<contents>`. Files:
- `logo-red.b64` (kyndryl coral logo, 120×40.32, PNG)
- `logo-white.b64` (white logo, PNG)
- `panel-white.b64` (white panel for thank-you page, PNG)
- `covers/dark-wave.b64` (PNG, 1900×1070, branding baked in),
  `covers/forest.b64`, `covers/globe.b64`, `covers/waves.b64` (JPEG,
  1900px wide photo covers — need scrim + branding cells, see Cover)
- `cover-art.b64` — legacy alias of `covers/dark-wave.b64`

## Workflow

1. Plan slides: Cover → Agenda → repeated [Section divider → content slides] →
   Thank-you ("99"). When the source is a .docx, parse tables too
   (`doc.tables` in python-docx, `w:tbl` in raw XML) — decision-dense content
   often lives in tables, not paragraphs.
2. Generate the XML with a script (python) that inlines the assets — never
   paste base64 by hand. Entity-escape `<` `>` `"` `&` in every `value=`
   attribute. Sanity-check geometry: no element outside the page canvas, no
   overlapping non-chrome bounding boxes, and every edge `source`/`target`
   id must exist.
3. Number pages "01", "02", … in the bottom-right cell; section dividers and
   agenda/cover carry no page number.
4. Validate: `python3 scripts/validate_deck.py <file.drawio>` — checks chrome
   geometry, fonts, arrow conventions, label spacing, cover scrim/title width,
   agenda column width, and the logo-contrast rule. New decks must report
   0 errors and aim for 0 warnings (the reference itself has historical
   drift and does not pass its own validator).
5. Eyeball at least one page against the reference deck before delivering:
   `python3 scripts/render_page.py <file.drawio> <page-name> out.png` renders
   an approximate preview (needs `pillow`); render the same page name from
   `references/policy-full-storyboard.drawio` and compare colors, chrome
   placement, and arrow/label look.
