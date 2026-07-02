---
theme: default
title: "Slidev × draw.io — Live Diagram Integration"
addons:
  - 'slidev-addon-drawio'
layout: cover
background: "linear-gradient(135deg, #1e3a5f 0%, #0f172a 100%)"
---

# Slidev × draw.io

**Live editable diagrams in your presentations**

<div style="color: #94a3b8; margin-top: 16px; font-size: 14px;">
  Two modes: embedded chart or full-page. Click "Edit" to modify live.
</div>

---
layout: default
---

# Embedded Diagram — Modern Theme

<DrawioEmbed
  src="/diagrams/system-architecture.drawio"
  height="380px"
  :editable="true"
  theme="modern"
/>

---
layout: default
---

# Embedded Diagram — Dark Theme

<DrawioEmbed
  src="/diagrams/system-architecture.drawio"
  height="380px"
  :editable="true"
  theme="dark"
/>

---
layout: default
---

# Embedded Diagram — Neon Theme

<DrawioEmbed
  src="/diagrams/system-architecture.drawio"
  height="380px"
  :editable="true"
  theme="neon"
/>

---
layout: default
---

# Embedded Diagram — Minimal Theme

<DrawioEmbed
  src="/diagrams/system-architecture.drawio"
  height="380px"
  :editable="true"
  theme="minimal"
/>

---
layout: drawio-full
src: /diagrams/system-architecture.drawio
editable: true
theme: modern
title: System Architecture — Full Page
---

---
layout: drawio-full
src: /diagrams/system-architecture.drawio
editable: true
theme: dark
title: System Architecture — Dark Theme
---

---
layout: default
---

# CI/CD Pipeline — Flowchart

<DrawioEmbed
  src="/diagrams/flowchart.drawio"
  height="400px"
  :editable="true"
  theme="modern"
/>

---
layout: drawio-full
src: /diagrams/mindmap.drawio
editable: true
theme: modern
title: Project Mind Map
---

---
layout: two-cols
---

# Side-by-Side Layout

Use `DrawioEmbed` anywhere — as a chart alongside content.

- Works in any Slidev layout
- Responds to container size
- All themes supported
- Live edit in any context

::right::

<DrawioEmbed
  src="/diagrams/system-architecture.drawio"
  height="340px"
  :editable="true"
  theme="modern"
  :shadow="true"
/>

---
layout: center
---

# How Live Editing Works

1. Click **Edit** on any diagram
2. The full draw.io editor opens in an overlay
3. Make your changes, click **Save & Exit**
4. The slide updates instantly — no page reload needed

The diagram XML is preserved in memory for the session.

---
layout: default
---

# DrawioEmbed Props Reference

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `src` | `string` | required | Path to `.drawio` file in `/public` |
| `width` | `string` | `"100%"` | Container width (any CSS value) |
| `height` | `string` | `"400px"` | Container height (any CSS value) |
| `editable` | `boolean` | `false` | Show Edit button |
| `theme` | `string` | `"modern"` | `modern` \| `dark` \| `neon` \| `minimal` |
| `border` | `boolean` | `true` | Show border |
| `shadow` | `boolean` | `true` | Show drop shadow |

---
layout: center
---

# DrawioFull Layout

Use in frontmatter to make a diagram fill the entire slide:

```yaml
---
layout: drawio-full
src: /diagrams/architecture.drawio
editable: true
theme: dark
title: Optional Title Overlay
---
```

No additional content needed — the diagram fills 100% of the slide.
