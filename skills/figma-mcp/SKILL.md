---
name: figma-mcp
description: CLI tool for reading Figma files, extracting design tokens, inspecting components and frames, exporting assets, and mapping components to code.
---
# Figma API

## Usage
```bash
python scripts/figma_api.py list_tools
python scripts/figma_api.py <tool> [args...]
```
File key is the string in the Figma URL: `figma.com/file/<FILE_KEY>/...`  
Node IDs from URLs use hyphens (`1-2`) — convert to colons (`1:2`) when passing to the script.

---

## Workflow

**Follow these steps in order.**

### 1. Orient
```bash
python scripts/figma_api.py get_design_context <file_key>
```
Always start here. Returns pages, all top-level frames with IDs, component count, and token types.  
Identify which frames are relevant before fetching anything else.

### 2. Inspect frames
```bash
python scripts/figma_api.py figma_read_nodes <file_key> <node_ids_csv> [depth]
```
Start with `depth=1` to see direct children. If a node shows `children: N (use depth↑ to expand)`, call again with that node ID at `depth=2`.  
Never fetch the full tree at once — drill down only into what you need.

### 3. Get a visual reference
```bash
python scripts/figma_api.py figma_export_images <file_key> <node_ids_csv> png 1
```
Export frames as PNG for visual reference. URLs expire in ~30 min — download immediately.  
Use as source of truth when validating the final implementation.

### 4. Download assets
```bash
python scripts/figma_api.py figma_export_images <file_key> <svg_ids_csv> svg
python scripts/figma_api.py figma_export_images <file_key> <img_ids_csv> png 2
```
Identify vectors and image nodes from step 2, then export and download before implementing.  
Do not use placeholder assets if the real ones are available.

### 5. Extract tokens
```bash
python scripts/figma_api.py figma_extract_styles <file_key>
python scripts/figma_api.py figma_search_components <file_key>
```
Get colors, typography, and component inventory before writing any CSS or components.

---

## If the response is too large

1. Run `get_design_context` to get the frame map
2. Identify the specific child node IDs you need
3. Fetch each section separately with `figma_read_nodes` at `depth=1`
4. Drill into `childCount > 0` nodes individually

---

## Common errors

| Error | Cause |
|---|---|
| `HTTP 403` | Token invalid — check `.env` has no quotes around the value |
| `HTTP 429` | Rate limited — wait a moment and retry |
| `no styles defined in this file` | Designer used hardcoded values instead of Figma Styles — extract colors from nodes manually |
| Node ID not found | You passed a hyphenated ID (`1-2`) — convert to colon (`1:2`) |