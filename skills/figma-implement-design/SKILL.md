---
name: figma-implement-design
description: Use this skill when the user wants to implement a Figma design into code.
dependencies: figma-mcp frontend-developer
---

# figma-implement-design

Full workflow to go from a Figma file to production-ready code.
Uses `figma_api.py` (from the `figma-mcp` skill) as the only data source.
Never guess values — every color, size, font, and asset must come from the file.

---

## Before you start

```bash
python scripts/figma_api.py list_tools   # confirm the script is reachable
```

If it fails, check that `SPM_FIGMA_TOKEN` is set in the project `.env`.

---

## Phase 1 — Orient

**Goal:** understand the file structure before touching anything else.

```bash
python scripts/figma_api.py get_design_context <file_key>
```

From the output, identify and note:
- Which **pages** exist and which one contains the target design
- Which **frames** are screens vs components vs documentation
- How many **components** and **token types** are defined

> **If the output is too large:** the file likely has many pages.
> Call `figma_read_nodes` on the target page ID at `depth=1` instead,
> to get only that page's direct children.

**Deliverable:** a short list of frame IDs you need to implement, nothing more.

---

## Phase 2 — Visual reference

**Goal:** get a PNG of each target frame before writing any code.

```bash
python scripts/figma_api.py figma_export_images <file_key> <frame_ids_csv> png 1
```

Download each URL immediately — they expire in ~30 min.
Keep these open as ground truth throughout the implementation.
Do not proceed without a visual reference.

> **If there are many frames:** export them one at a time rather than all at once.
> A single failed URL is easier to retry than a batch.

---

## Phase 3 — Design tokens

**Goal:** extract all global values before writing a single line of CSS.

```bash
python scripts/figma_api.py figma_extract_styles <file_key>
```

Map the output into a tokens file (`tokens.css`, `tokens.ts`, or equivalent):

```css
/* tokens.css */
:root {
  /* Colors */
  --color-primary: #1D4ED8;

  /* Typography */
  --font-size-heading-1: 48px;
  --font-weight-heading-1: 700;
  --line-height-heading-1: 56px;
  --font-family-body: 'Inter', sans-serif;
}
```

> **If `figma_extract_styles` returns empty or partial results:**
> the file uses hardcoded values instead of Figma Styles.
> Fall back to extracting values directly from nodes in Phase 4 —
> inspect `.fills`, `.style`, `.strokeWeight` on individual nodes.
> Never invent values.

**Deliverable:** a committed tokens file. Do not proceed until it exists.

---

## Phase 4 — Component inventory

**Goal:** know every reusable piece before building anything.

```bash
python scripts/figma_api.py figma_search_components <file_key>
```

For each component set (variants), note:
- Component name and node ID
- Variant properties (e.g. `size=sm|md|lg`, `state=default|hover|disabled`)

Then inspect the ones you need to implement:

```bash
python scripts/figma_api.py figma_read_nodes <file_key> <component_ids_csv> 1
```

Start at `depth=1`. If a node shows `childCount > 0`, drill in:

```bash
python scripts/figma_api.py figma_read_nodes <file_key> <child_id> 2
```

> **Depth discipline — strictly follow this order:**
> 1. `depth=1` — see direct children and layout props
> 2. If needed, `depth=2` on a specific child
> 3. Never request `depth=3+` on a large node — split into smaller calls instead
>
> **If a response is too large to process:**
> — identify the `childCount` nodes that are relevant
> — fetch each one individually at `depth=1`
> — delegate complex components to a focused sub-call scoped to that component ID only

**Deliverable:** a list mapping each Figma component to its code counterpart.

---

## Phase 5 — Asset extraction

**Goal:** download every icon, illustration, and image before layout work.

From Phase 4 node inspection, identify:
- Vector nodes (type `VECTOR`, `BOOLEAN_OPERATION`) → export as SVG
- Image fills (type `RECTANGLE` with `imageRef`) → export as PNG @2x

```bash
# Vectors
python scripts/figma_api.py figma_export_images <file_key> <vector_ids_csv> svg

# Raster images
python scripts/figma_api.py figma_export_images <file_key> <image_ids_csv> png 2
```

Download all URLs immediately. Place assets in `assets/icons/` and `assets/images/`.
Never use a placeholder if the real asset is available.

> **If there are 20+ assets:** batch by type (all icons in one call, all images in another).
> If a batch fails with `HTTP 429`, split it in half and retry each part separately.

---

## Phase 6 — UI kit

**Goal:** build every component in isolation before composing layouts.

Order of implementation:
1. **Primitives** — tokens already done; now build base elements (Button, Input, Badge, Icon)
2. **Composites** — components made of primitives (Card, Modal, NavItem)
3. **Sections** — full-width layout sections (Header, Hero, Footer)

For each component:
- Match the Figma node structure as closely as the target framework allows
- Use token variables — never hardcode a color or size that exists in tokens
- Implement all variants defined in the component set
- Check against the visual reference from Phase 2

> **If a component has many variants (10+):**
> implement the default state first, ship it, then layer in variants.
> Do not block layout work on exhaustive variant coverage.

---

## Phase 7 — Layout

**Goal:** compose the full page using the components from Phase 6.

```bash
python scripts/figma_api.py figma_read_nodes <file_key> <screen_frame_id> 1
```

Read the top-level layout of the target screen at `depth=1`.
Map each direct child to a component or section from Phase 6.

Then inspect each section individually:

```bash
python scripts/figma_api.py figma_read_nodes <file_key> <section_id> 2
```

Implement the layout using the exact values from the node:
- `absoluteBoundingBox` → width, height, position
- `paddingLeft/Right/Top/Bottom` → padding
- `itemSpacing` → gap
- `layoutMode` → `HORIZONTAL` = `flex-row`, `VERTICAL` = `flex-col`
- `primaryAxisAlignItems` / `counterAxisAlignItems` → justify/align

> **If the screen is very long (e.g. a landing page with 8+ sections):**
> split into vertical slices. Implement and review one section at a time.
> Never try to map the entire page in a single node fetch.

---

## Phase 8 — Review

**Goal:** close the gap between the implementation and the Figma reference.

Go through each screen with the Phase 2 PNG open side by side and check:

| Area | What to verify |
|---|---|
| Spacing | Margins, padding, gaps match the node values |
| Typography | Font family, size, weight, line-height, letter-spacing |
| Color | Every fill, border, and shadow matches a token or extracted value |
| Assets | No placeholders — every icon and image is the real asset |
| Variants | Interactive states (hover, focus, disabled) are implemented |
| Responsive | Layout holds at the breakpoints implied by the Figma frames |

Fix any delta. Re-export a PNG of the implementation if possible and diff visually.

---

## Error reference

| Error | What to do |
|---|---|
| `HTTP 403` | `SPM_FIGMA_TOKEN` is wrong or expired — regenerate in Figma account settings |
| `HTTP 429` | Rate limited — wait 10–15 seconds, then retry; reduce batch size |
| `no styles defined` | Use node-level value extraction in Phase 4 instead |
| Node ID not found | You passed a hyphenated ID (`1-2`) — convert to colon (`1:2`) |
| Response too large | Drop depth by 1 and re-fetch; split into smaller node ID batches |
| Export URL expired | Re-run `figma_export_images` and download within 30 min |