#!/usr/bin/env python3
"""
figma_api.py — Figma API tool runner
Token read from SPM_FIGMA_TOKEN environment variable.

Usage:
  python figma_api.py <tool> [args...]

Tools:
  list_tools
  get_design_context      <file_key>
  get_metadata            <file_key>
  figma_read_nodes        <file_key> <node_ids_csv> [depth]
  figma_extract_styles    <file_key> [types_csv]
  figma_search_components <file_key> [query]
  figma_export_images     <file_key> <node_ids_csv> [format] [scale]
  create_design_system_rules <file_key> [text|css|markdown]
  generate_figma_design   <file_key> <spec>
  get_code_connect_map    <file_key> [component_id]
  add_code_connect_map    <file_key> <component_id> <name> <code_path> [framework]
"""

import os, sys, json, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = "https://api.figma.com/v1"

# ── Env ───────────────────────────────────────────────────────────────────────

ENV_VARS = ["SPM_FIGMA_TOKEN"]

def _load_env():
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        return
    declared = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            declared[k.strip()] = v.strip().strip('"').strip("'")
    for key in ENV_VARS:
        if key in declared:
            os.environ.setdefault(key, declared[key])

_load_env()

# ── HTTP ──────────────────────────────────────────────────────────────────────

def _token():
    t = os.environ.get("SPM_FIGMA_TOKEN", "")
    if not t:
        sys.exit("Error: SPM_FIGMA_TOKEN environment variable not set")
    return t

def get(path):
    url = BASE + path
    req = urllib.request.Request(url, headers={
        "X-Figma-Token": _token(),
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise Exception(f"HTTP {e.code} {e.reason}: {body}")

def parallel(*paths):
    results = [None] * len(paths)
    def fetch(i, p):
        try:    return i, get(p), None
        except Exception as e: return i, None, e
    with ThreadPoolExecutor(max_workers=len(paths)) as ex:
        futs = [ex.submit(fetch, i, p) for i, p in enumerate(paths)]
        for f in as_completed(futs):
            i, data, err = f.result()
            results[i] = (data, err)
    return results

# ── Utils ─────────────────────────────────────────────────────────────────────

def prune(node, depth):
    """Return the raw Figma node pruned to depth. No transformations."""
    if not node: return None
    out = {k: v for k, v in node.items() if k != "children"}
    children = node.get("children", [])
    if depth > 0 and children:
        out["children"] = [prune(c, depth - 1) for c in children]
    elif children:
        out["childCount"] = len(children)
    return out

# ── Tools ─────────────────────────────────────────────────────────────────────

def tool_list_tools():
    return __doc__.strip()

def tool_get_design_context(file_key):
    results = parallel(
        f"/files/{file_key}?depth=2",
        f"/files/{file_key}/styles",
        f"/files/{file_key}/components",
        f"/files/{file_key}/component_sets",
    )
    f_data, f_err = results[0]
    if f_err: return f"Error: {f_err}"
    styles    = (results[1][0] or {}).get("meta",{}).get("styles",[])
    comp_cnt  = len((results[2][0] or {}).get("meta",{}).get("components",[]))
    sets_cnt  = len((results[3][0] or {}).get("meta",{}).get("component_sets",[]))

    token_counts = {}
    for s in styles:
        st = s["style_type"]
        token_counts[st] = token_counts.get(st, 0) + 1

    lines = [
        f'{f_data["name"]}  |  modified: {f_data["lastModified"][:10]}',
        f'components: {comp_cnt}  variant-sets: {sets_cnt}  tokens: {json.dumps(token_counts)}',
        "",
    ]
    for page in f_data.get("document",{}).get("children",[]):
        frames = [n for n in page.get("children",[])
                  if n["type"] in ("FRAME","COMPONENT","COMPONENT_SET","SECTION","GROUP")]
        lines.append(f'PAGE  {page["id"]}  "{page["name"]}"  ({len(frames)} frames)')
        for fr in frames:
            lines.append(f'  {fr["id"]:<12}  {fr["type"]:<14}  {fr["name"]}')
        lines.append("")
    return "\n".join(lines).rstrip()

def tool_get_metadata(file_key):
    results = parallel(f"/files/{file_key}?depth=1", f"/files/{file_key}/collaborators")
    f_data, f_err = results[0]
    if f_err: return f"Error: {f_err}"
    collabs = (results[1][0] or {}).get("collaborators", [])
    lines = [
        f_data["name"],
        f'key:      {file_key}',
        f'version:  {f_data["version"]}',
        f'modified: {f_data["lastModified"][:10]}',
        f'type:     {f_data.get("editorType","figma")}',
    ]
    if f_data.get("owner"): lines.append(f'owner:    {f_data["owner"]["handle"]}')
    if collabs:
        lines.append("")
        lines.append("collaborators:")
        for c in collabs:
            lines.append(f'  {c["role"]:<12}  {c["handle"]}')
    return "\n".join(lines)

def tool_figma_read_nodes(file_key, node_ids_csv, depth=2):
    ids  = urllib.parse.quote(node_ids_csv)
    data = get(f"/files/{file_key}/nodes?ids={ids}")
    nodes = {
        id_: prune(val.get("document"), int(depth))
        for id_, val in (data.get("nodes") or {}).items()
    }
    return json.dumps(nodes, indent=2)

def tool_figma_extract_styles(file_key, types_csv=None):
    raw    = get(f"/files/{file_key}/styles")
    styles = raw.get("meta",{}).get("styles",[])
    if types_csv:
        types = [t.strip() for t in types_csv.split(",")]
        styles = [s for s in styles if s["style_type"] in types]
    if not styles: return "no styles defined in this file"

    fills = [s for s in styles if s["style_type"] == "FILL"]
    texts = [s for s in styles if s["style_type"] == "TEXT"]

    colors = [{"name": s["name"]} for s in fills]
    if fills:
        try:
            ids   = urllib.parse.quote(",".join(s["node_id"] for s in fills))
            nodes = get(f"/files/{file_key}/nodes?ids={ids}")
            colors = []
            for s in fills:
                doc   = (nodes.get("nodes",{}).get(s["node_id"]) or {}).get("document",{})
                f_lst = [f for f in doc.get("fills",[]) if f.get("type")=="SOLID" and f.get("visible",True)]
                hex_  = to_hex(f_lst[0]["color"]) if f_lst else "?"
                entry = {"name": s["name"], "hex": hex_}
                if f_lst and f_lst[0].get("opacity",1) < 1:
                    entry["opacity"] = f_lst[0]["opacity"]
                colors.append(entry)
        except: pass

    typography = [{"name": s["name"]} for s in texts]
    if texts:
        try:
            ids   = urllib.parse.quote(",".join(s["node_id"] for s in texts))
            nodes = get(f"/files/{file_key}/nodes?ids={ids}")
            typography = []
            for s in texts:
                doc  = (nodes.get("nodes",{}).get(s["node_id"]) or {}).get("document",{})
                typo = to_typo(doc.get("style",{}))
                typography.append({"name": s["name"], **typo})
        except: pass

    effects = [s["name"] for s in styles if s["style_type"] == "EFFECT"]
    grids   = [s["name"] for s in styles if s["style_type"] == "GRID"]

    lines = []
    if colors:
        lines.append("COLORS")
        for c in colors:
            op = f'  opacity:{c["opacity"]}' if c.get("opacity") else ""
            lines.append(f'  {c["hex"]:<10}  {c["name"]}{op}')
        lines.append("")
    if typography:
        lines.append("TYPOGRAPHY")
        for t in typography:
            parts = [
                f'{t["size"]}px'   if t.get("size")   else None,
                f'w{t["weight"]}'  if t.get("weight") else None,
                f'lh{t["lh"]}'     if t.get("lh")     else None,
                t.get("family"),
                t.get("case"),
                f'ls{t["ls"]}'     if t.get("ls")     else None,
            ]
            lines.append(f'  {t["name"]:<28}  {"  ".join(p for p in parts if p)}')
        lines.append("")
    if effects:
        lines.append("EFFECTS")
        for n in effects: lines.append(f"  {n}")
        lines.append("")
    if grids:
        lines.append("GRIDS")
        for n in grids: lines.append(f"  {n}")
    return "\n".join(lines).rstrip()

def tool_figma_search_components(file_key, query=None):
    results = parallel(f"/files/{file_key}/components", f"/files/{file_key}/component_sets")
    comps = (results[0][0] or {}).get("meta",{}).get("components",[])
    sets  = (results[1][0] or {}).get("meta",{}).get("component_sets",[])
    if query:
        q     = query.lower()
        comps = [c for c in comps if q in c["name"].lower()]
        sets  = [s for s in sets  if q in s["name"].lower()]
    if not comps and not sets: return "no components found"
    lines = []
    if sets:
        lines.append("VARIANT SETS")
        for s in sets: lines.append(f'  {s["node_id"]:<12}  {s["name"]}')
        lines.append("")
    if comps:
        lines.append("COMPONENTS")
        for c in comps:
            desc = f'  — {c["description"]}' if c.get("description") else ""
            lines.append(f'  {c["node_id"]:<12}  {c["name"]}{desc}')
    lines.append(f'\ntotal: {len(comps)+len(sets)}')
    return "\n".join(lines)

def tool_figma_export_images(file_key, node_ids_csv, format="png", scale=1):
    ids  = urllib.parse.quote(node_ids_csv)
    data = get(f"/images/{file_key}?ids={ids}&format={format}&scale={scale}")
    if data.get("err"): return f"Error: {data['err']}"
    images = list((data.get("images") or {}).items())
    if not images: return "no images returned"
    lines = [f"format:{format}  scale:{scale}  expires:~30min", ""]
    for id_, url in images:
        lines.append(f"{id_}\n  {url}")
    return "\n".join(lines)

def tool_create_design_system_rules(file_key, format="text"):
    results = parallel(
        f"/files/{file_key}/styles",
        f"/files/{file_key}/components",
        f"/files/{file_key}/component_sets",
    )
    styles    = (results[0][0] or {}).get("meta",{}).get("styles",[])
    comps     = (results[1][0] or {}).get("meta",{}).get("components",[])
    sets      = (results[2][0] or {}).get("meta",{}).get("component_sets",[])
    fills     = [s for s in styles if s["style_type"]=="FILL"]
    texts     = [s for s in styles if s["style_type"]=="TEXT"]

    colors = []
    if fills:
        try:
            ids   = urllib.parse.quote(",".join(s["node_id"] for s in fills))
            nodes = get(f"/files/{file_key}/nodes?ids={ids}")
            for s in fills:
                doc = (nodes.get("nodes",{}).get(s["node_id"]) or {}).get("document",{})
                f_  = [f for f in doc.get("fills",[]) if f.get("type")=="SOLID"]
                colors.append({"name": s["name"], "hex": to_hex(f_[0]["color"]) if f_ else "?"})
        except: colors = [{"name":s["name"]} for s in fills]

    typography = []
    if texts:
        try:
            ids   = urllib.parse.quote(",".join(s["node_id"] for s in texts))
            nodes = get(f"/files/{file_key}/nodes?ids={ids}")
            for s in texts:
                doc  = (nodes.get("nodes",{}).get(s["node_id"]) or {}).get("document",{})
                typo = to_typo(doc.get("style",{}))
                typography.append({"name": s["name"], **typo})
        except: typography = [{"name":s["name"]} for s in texts]

    comp_names = [c["name"] for c in comps]
    set_names  = [s["name"] for s in sets]

    if format == "css":
        lines = [":root {"]
        for c in colors:
            if c.get("hex"):
                tok = c["name"].lower().replace(" ","-")
                lines.append(f'  --color-{tok}: {c["hex"]};')
        for t in typography:
            tok = t["name"].lower().replace(" ","-")
            if t.get("size"):   lines.append(f'  --font-size-{tok}: {t["size"]}px;')
            if t.get("weight"): lines.append(f'  --font-weight-{tok}: {t["weight"]};')
            if t.get("lh"):     lines.append(f'  --line-height-{tok}: {t["lh"]}px;')
            if t.get("family"): lines.append(f'  --font-family-{tok}: {t["family"]};')
        lines.append("}")
        return "\n".join(lines)

    if format == "markdown":
        lines = ["# Design System\n"]
        if colors:
            lines.append("## Colors")
            for c in colors: lines.append(f'- **{c["name"]}** `{c.get("hex","")}`')
            lines.append("")
        if typography:
            lines.append("## Typography")
            for t in typography:
                detail = "  ".join(p for p in [
                    f'{t["size"]}px' if t.get("size") else None,
                    f'w{t["weight"]}' if t.get("weight") else None,
                    t.get("family"),
                ] if p)
                lines.append(f'- **{t["name"]}** {detail}')
            lines.append("")
        if comp_names:
            lines.append("## Components")
            for n in comp_names: lines.append(f"- {n}")
        return "\n".join(lines)

    # text (default)
    lines = []
    if colors:
        lines.append("COLORS")
        for c in colors: lines.append(f'  {(c.get("hex","?")):<10}  {c["name"]}')
        lines.append("")
    if typography:
        lines.append("TYPOGRAPHY")
        for t in typography:
            parts = "  ".join(p for p in [
                f'{t["size"]}px' if t.get("size") else None,
                f'w{t["weight"]}' if t.get("weight") else None,
                f'lh{t["lh"]}' if t.get("lh") else None,
                t.get("family"),
            ] if p)
            lines.append(f'  {t["name"]:<28}  {parts}')
        lines.append("")
    if comp_names:
        lines.append("COMPONENTS")
        for n in comp_names: lines.append(f"  {n}")
        lines.append("")
    if set_names:
        lines.append("VARIANT SETS")
        for n in set_names: lines.append(f"  {n}")
    return "\n".join(lines).rstrip() or "no styles or components found"

def tool_generate_figma_design(file_key, spec):
    results = parallel(
        f"/files/{file_key}/styles",
        f"/files/{file_key}/components",
        f"/files/{file_key}/component_sets",
    )
    styles = (results[0][0] or {}).get("meta",{}).get("styles",[])
    fills  = [s for s in styles if s["style_type"]=="FILL"]
    texts  = [s for s in styles if s["style_type"]=="TEXT"]
    comps  = [(c["node_id"], c["name"]) for c in (results[1][0] or {}).get("meta",{}).get("components",[])]
    sets   = [(s["node_id"], s["name"]) for s in (results[2][0] or {}).get("meta",{}).get("component_sets",[])]

    colors = []
    if fills:
        try:
            ids   = urllib.parse.quote(",".join(s["node_id"] for s in fills))
            nodes = get(f"/files/{file_key}/nodes?ids={ids}")
            for s in fills:
                doc = (nodes.get("nodes",{}).get(s["node_id"]) or {}).get("document",{})
                f_  = [f for f in doc.get("fills",[]) if f.get("type")=="SOLID"]
                colors.append({"name":s["name"],"hex":to_hex(f_[0]["color"]) if f_ else None})
        except: colors = [{"name":s["name"]} for s in fills]

    words  = [w for w in spec.lower().split() if len(w) > 2]
    score  = lambda name: sum(1 for w in words if w in name.lower())
    SEMANTIC = {"primary","secondary","background","surface","text","border","error","success","warning"}

    matched_comps = sorted(
        [(id_, n, score(n)) for id_, n in comps+sets if score(n) > 0],
        key=lambda x: -x[2]
    )
    matched_colors = sorted(
        [(c, score(c["name"]) + sum(1 for w in SEMANTIC if w in c["name"].lower())) for c in colors if score(c["name"]) > 0],
        key=lambda x: -x[1]
    )[:5]

    s = spec.lower()
    if   "modal" in s or "dialog"  in s: layout = ("overlay", 480,    24)
    elif "card"  in s:                   layout = ("card",    360,    16)
    elif "sidebar" in s or "nav" in s:   layout = ("sidebar", 240,    16)
    elif "banner" in s or "hero" in s:   layout = ("banner", "100%",  48)
    elif "form"  in s or "login" in s:   layout = ("form",   400,    32)
    elif "list"  in s or "table" in s:   layout = ("list",  "100%",  16)
    elif "page"  in s or "screen" in s:  layout = ("page",  1440,     0)
    else:                                layout = ("frame",  800,    24)

    lines = [
        f'spec: "{spec}"',
        f'layout: {layout[0]}  w:{layout[1]}  padding:{layout[2]}px',
        "",
    ]
    if matched_comps:
        lines.append("MATCHED COMPONENTS")
        for id_, name, _ in matched_comps:
            lines.append(f'  {id_:<12}  {name}')
        lines.append("")
    else:
        lines.append("no components matched" if comps else "no published components in file")
        lines.append("")
    if matched_colors:
        lines.append("MATCHED COLORS")
        for c, _ in matched_colors:
            lines.append(f'  {(c.get("hex") or "?"):<10}  {c["name"]}')
        lines.append("")
    if matched_comps:
        lines.append("→ use figma_read_nodes with component IDs to inspect details")
    return "\n".join(lines).rstrip()

def tool_get_code_connect_map(file_key, component_id=None):
    map_file = os.path.join(os.getcwd(), "code-connect.json")
    try:
        with open(map_file) as f: map_ = json.load(f)
    except: map_ = {}
    entry = map_.get(file_key, {})
    if component_id:
        m = entry.get(component_id)
        if not m: return f"not found: {component_id}"
        return f'{component_id}  {m["name"]}\n  path: {m["codePath"]}\n  framework: {m.get("framework","?")}'
    rows = list(entry.items())
    if not rows: return "no mappings for this file"
    lines = [f"code-connect  ({len(rows)} components)", ""]
    for id_, d in rows:
        lines.append(f'{id_:<12}  {d["name"]}')
        lines.append(f'              {d["codePath"]}  [{d.get("framework","?")}]')
    return "\n".join(lines)

def tool_add_code_connect_map(file_key, component_id, name, code_path, framework=None):
    from datetime import date
    map_file = os.path.join(os.getcwd(), "code-connect.json")
    try:
        with open(map_file) as f: map_ = json.load(f)
    except: map_ = {}
    if file_key not in map_: map_[file_key] = {}
    existing = map_[file_key].get(component_id)
    map_[file_key][component_id] = {
        "name":      name,
        "codePath":  code_path,
        "framework": framework or (existing or {}).get("framework"),
        "updatedAt": str(date.today()),
    }
    with open(map_file, "w") as f: json.dump(map_, f, indent=2)
    action = "updated" if existing else "created"
    return f'{action}  {component_id}  {name}\n  path: {code_path}\n  framework: {framework or "?"}'

# ── Dispatch ──────────────────────────────────────────────────────────────────

TOOLS = {
    "list_tools":                  (tool_list_tools,                 0, 0),
    "get_design_context":          (tool_get_design_context,         1, 1),
    "get_metadata":                (tool_get_metadata,               1, 1),
    "figma_read_nodes":            (tool_figma_read_nodes,           2, 3),
    "figma_extract_styles":        (tool_figma_extract_styles,       1, 2),
    "figma_search_components":     (tool_figma_search_components,    1, 2),
    "figma_export_images":         (tool_figma_export_images,        2, 4),
    "create_design_system_rules":  (tool_create_design_system_rules, 1, 2),
    "generate_figma_design":       (tool_generate_figma_design,      2, 2),
    "get_code_connect_map":        (tool_get_code_connect_map,       1, 2),
    "add_code_connect_map":        (tool_add_code_connect_map,       4, 5),
}

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    tool_name = args[0]
    if tool_name not in TOOLS:
        sys.exit(f"Unknown tool: {tool_name}\nRun: python figma_api.py list_tools")

    fn, min_args, max_args = TOOLS[tool_name]
    call_args = args[1:]

    if len(call_args) < min_args or len(call_args) > max_args:
        sys.exit(f"Usage error: {tool_name} expects {min_args}–{max_args} args, got {len(call_args)}")

    try:
        print(fn(*call_args))
    except Exception as e:
        sys.exit(f"Error: {e}")