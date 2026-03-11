#!/usr/bin/env python3
"""
figma_mcp.py — Figma MCP Server
Token read from BRAIN_FIGMA_TOKEN environment variable.
"""

import subprocess
import sys

def _ensure_deps():
    required = ["mcp[cli]", "python-dotenv"]
    missing = []
    for pkg in required:
        import_name = pkg.split("[")[0].replace("-", "_")
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[figma_mcp] installing: {' '.join(missing)}", file=sys.stderr)
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "--break-system-packages"] + missing
        )

_ensure_deps()

import os
import json
import urllib.request
import urllib.parse
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from dotenv import load_dotenv

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict

# ── Env ───────────────────────────────────────────────────────────────────────

load_dotenv()

# ── Constants ─────────────────────────────────────────────────────────────────

BASE = "https://api.figma.com/v1"

# ── HTTP ──────────────────────────────────────────────────────────────────────

def _token() -> str:
    t = os.environ.get("BRAIN_FIGMA_TOKEN", "")
    if not t:
        raise ValueError("BRAIN_FIGMA_TOKEN environment variable not set")
    return t


def get(path: str) -> dict:
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
        if e.code == 429:
            retry_after = e.headers.get("Retry-After")
            limit = e.headers.get("X-RateLimit-Limit")
            remaining = e.headers.get("X-RateLimit-Remaining")
            reset_epoch = e.headers.get("X-RateLimit-Reset")

            details = ["Rate limit exceeded (HTTP 429)."]
            details.append("Figma allows ~60 req/min on paid plans, fewer on free plans.")
            if limit:
                details.append(f"  Limit:     {limit} requests/min")
            if remaining is not None:
                details.append(f"  Remaining: {remaining} requests")
            if reset_epoch:
                import datetime
                try:
                    reset_dt = datetime.datetime.fromtimestamp(int(reset_epoch), tz=datetime.timezone.utc)
                    now = datetime.datetime.now(tz=datetime.timezone.utc)
                    wait_sec = max(0, int((reset_dt - now).total_seconds()))
                    details.append(f"  Resets at: {reset_dt.strftime('%H:%M:%S UTC')} (~{wait_sec}s from now)")
                except ValueError:
                    details.append(f"  Resets at: {reset_epoch} (epoch)")
            if retry_after:
                details.append(f"  Retry-After: {retry_after}s")
            details.append("Tip: batch node IDs in a single call to reduce request count.")
            raise Exception("\n".join(details))
        raise Exception(f"HTTP {e.code} {e.reason}: {body}")


def parallel(*paths: str) -> list:
    results = [None] * len(paths)

    def fetch(i: int, p: str):
        try:
            return i, get(p), None
        except Exception as e:
            return i, None, e

    with ThreadPoolExecutor(max_workers=len(paths)) as ex:
        futs = [ex.submit(fetch, i, p) for i, p in enumerate(paths)]
        for f in as_completed(futs):
            i, data, err = f.result()
            results[i] = (data, err)
    return results


# ── Utils ─────────────────────────────────────────────────────────────────────

def prune(node: dict, depth: int) -> Optional[dict]:
    """Return the raw Figma node pruned to depth. No transformations."""
    if not node:
        return None
    out = {k: v for k, v in node.items() if k != "children"}
    children = node.get("children", [])
    if depth > 0 and children:
        out["children"] = [prune(c, depth - 1) for c in children]
    elif children:
        out["childCount"] = len(children)
    return out


def to_hex(color: dict) -> str:
    """Convert Figma color (r,g,b in 0-1) to hex string."""
    r, g, b = color.get("r", 0), color.get("g", 0), color.get("b", 0)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def to_typo(style: dict) -> dict:
    """Extract typography properties from Figma text style."""
    return {
        "family": style.get("fontFamily"),
        "size": style.get("fontSize"),
        "weight": style.get("fontWeight"),
        "lh": style.get("lineHeightPx"),
        "ls": style.get("letterSpacing"),
        "case": style.get("textCase"),
    }


def parse_figma_input(value: str) -> tuple[str, str]:
    """Accept a raw file key OR any Figma URL and return (file_key, dev_url).

    Supported URL shapes:
      https://www.figma.com/file/<key>/...
      https://www.figma.com/design/<key>/...
      https://www.figma.com/proto/<key>/...
      https://figma.com/...  (no www)

    If the URL is missing ?mode=dev the returned dev_url will have it appended.
    If a bare file key is passed the dev_url is constructed from scratch.
    """
    value = value.strip()

    # bare key — no slashes, no protocol
    if "figma.com" not in value:
        file_key = value
        dev_url = f"https://www.figma.com/design/{file_key}?mode=dev"
        return file_key, dev_url

    parsed = urllib.parse.urlparse(value)
    # path looks like  /file/<key>/Title   or   /design/<key>/Title
    parts = [p for p in parsed.path.split("/") if p]
    # parts[0] = "file" | "design" | "proto", parts[1] = file_key
    if len(parts) < 2:
        raise ValueError(f"Cannot extract file key from URL: {value}")

    file_key = parts[1]

    # rebuild query, ensuring mode=dev is present
    qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    qs["mode"] = ["dev"]
    new_query = urllib.parse.urlencode({k: v[0] for k, v in qs.items()})

    dev_url = urllib.parse.urlunparse((
        parsed.scheme or "https",
        parsed.netloc or "www.figma.com",
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment,
    ))
    return file_key, dev_url


# ── MCP Server ────────────────────────────────────────────────────────────────

mcp = FastMCP("figma_mcp")

# ── Input Models ──────────────────────────────────────────────────────────────

_FILE_KEY_DESC = (
    "Figma file key OR a full Figma URL "
    "(e.g. https://www.figma.com/design/ABC123/...). "
    "URLs without ?mode=dev will have it added automatically."
)


def resolve(value: str) -> tuple[str, str]:
    """Parse a raw key or any Figma URL -> (file_key, dev_url)."""
    return parse_figma_input(value)


class FileKeyInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    file_key: str = Field(..., description=_FILE_KEY_DESC)


class ReadNodesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    file_key: str = Field(..., description=_FILE_KEY_DESC)
    node_ids_csv: str = Field(..., description="Comma-separated list of node IDs to read")
    depth: int = Field(default=2, description="Depth of node tree to return", ge=1, le=10)


class ExtractStylesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    file_key: str = Field(..., description=_FILE_KEY_DESC)
    types_csv: Optional[str] = Field(
        default=None,
        description="Comma-separated style types to filter by (e.g. 'FILL,TEXT'). Options: FILL, TEXT, EFFECT, GRID"
    )


class SearchComponentsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    file_key: str = Field(..., description=_FILE_KEY_DESC)
    query: Optional[str] = Field(default=None, description="Search query to filter components by name")


class ExportImagesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    file_key: str = Field(..., description=_FILE_KEY_DESC)
    node_ids_csv: str = Field(..., description="Comma-separated list of node IDs to export")
    format: str = Field(default="png", description="Export format: png, jpg, svg, or pdf")
    scale: float = Field(default=1.0, description="Export scale multiplier (e.g. 2 for 2x)", ge=0.01, le=4.0)


class DesignSystemRulesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    file_key: str = Field(..., description=_FILE_KEY_DESC)
    format: str = Field(
        default="text",
        description="Output format: 'text' (default), 'css' (CSS custom properties), or 'markdown'"
    )


class GenerateDesignInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    file_key: str = Field(..., description=_FILE_KEY_DESC)
    spec: str = Field(..., description="Natural language design spec (e.g. 'login modal with email and password fields')")


class CodeConnectGetInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    file_key: str = Field(..., description=_FILE_KEY_DESC)
    component_id: Optional[str] = Field(default=None, description="Specific component ID to look up")


class CodeConnectAddInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    file_key: str = Field(..., description=_FILE_KEY_DESC)
    component_id: str = Field(..., description="Figma component node ID")
    name: str = Field(..., description="Component name")
    code_path: str = Field(..., description="Path to the component's code file")
    framework: Optional[str] = Field(default=None, description="Framework identifier (e.g. 'react', 'vue', 'swift')")


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="figma_get_design_context",
    annotations={
        "title": "Get Design Context",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def figma_get_design_context(params: FileKeyInput) -> str:
    """Get a high-level overview of a Figma file: pages, frames, component counts, and design token summary.

    Returns a structured text overview including file name, last modified date, component/variant-set
    counts, token type breakdown, and a per-page list of top-level frames with their node IDs and types.

    Args:
        params (FileKeyInput): Input containing:
            - file_key (str): Figma file key from the file URL

    Returns:
        str: Formatted text with file metadata, design token counts, and page/frame hierarchy
    """
    file_key, dev_url = resolve(params.file_key)
    results = parallel(
        f"/files/{file_key}?depth=2",
        f"/files/{file_key}/styles",
        f"/files/{file_key}/components",
        f"/files/{file_key}/component_sets",
    )
    f_data, f_err = results[0]
    if f_err:
        return f"Error: {f_err}"

    styles = (results[1][0] or {}).get("meta", {}).get("styles", [])
    comp_cnt = len((results[2][0] or {}).get("meta", {}).get("components", []))
    sets_cnt = len((results[3][0] or {}).get("meta", {}).get("component_sets", []))

    token_counts = {}
    for s in styles:
        st = s["style_type"]
        token_counts[st] = token_counts.get(st, 0) + 1

    lines = [
        f'{f_data["name"]}  |  modified: {f_data["lastModified"][:10]}',
        f'dev_url: {dev_url}',
        f'components: {comp_cnt}  variant-sets: {sets_cnt}  tokens: {json.dumps(token_counts)}',
        "",
    ]
    for page in f_data.get("document", {}).get("children", []):
        frames = [
            n for n in page.get("children", [])
            if n["type"] in ("FRAME", "COMPONENT", "COMPONENT_SET", "SECTION", "GROUP")
        ]
        lines.append(f'PAGE  {page["id"]}  "{page["name"]}"  ({len(frames)} frames)')
        for fr in frames:
            lines.append(f'  {fr["id"]:<12}  {fr["type"]:<14}  {fr["name"]}')
        lines.append("")
    return "\n".join(lines).rstrip()


@mcp.tool(
    name="figma_get_metadata",
    annotations={
        "title": "Get File Metadata",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def figma_get_metadata(params: FileKeyInput) -> str:
    """Get metadata for a Figma file including name, version, owner, and collaborators.

    Args:
        params (FileKeyInput): Input containing:
            - file_key (str): Figma file key

    Returns:
        str: Formatted text with file name, key, version, last-modified date, editor type,
             owner handle, and a list of collaborators with their roles
    """
    file_key, dev_url = resolve(params.file_key)
    results = parallel(f"/files/{file_key}?depth=1", f"/files/{file_key}/collaborators")
    f_data, f_err = results[0]
    if f_err:
        return f"Error: {f_err}"

    collabs = (results[1][0] or {}).get("collaborators", [])
    lines = [
        f_data["name"],
        f'key:      {file_key}',
        f'version:  {f_data["version"]}',
        f'modified: {f_data["lastModified"][:10]}',
        f'type:     {f_data.get("editorType", "figma")}',
    ]
    if f_data.get("owner"):
        lines.append(f'owner:    {f_data["owner"]["handle"]}')
    if collabs:
        lines.append("")
        lines.append("collaborators:")
        for c in collabs:
            lines.append(f'  {c["role"]:<12}  {c["handle"]}')
    return "\n".join(lines)


@mcp.tool(
    name="figma_read_nodes",
    annotations={
        "title": "Read Nodes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def figma_read_nodes(params: ReadNodesInput) -> str:
    """Read and inspect specific Figma nodes by their IDs, returning their raw properties pruned to a given depth.

    Batch multiple node IDs in one call to minimize API requests.

    Args:
        params (ReadNodesInput): Input containing:
            - file_key (str): Figma file key
            - node_ids_csv (str): Comma-separated node IDs (e.g. '1:2,3:4,5:6')
            - depth (int): Tree depth to return (default: 2, range: 1-10)

    Returns:
        str: JSON object keyed by node ID, each value being the pruned node tree
    """
    ids = urllib.parse.quote(params.node_ids_csv)
    data = get(f"/files/{params.file_key}/nodes?ids={ids}")
    nodes = {
        id_: prune(val.get("document"), params.depth)
        for id_, val in (data.get("nodes") or {}).items()
    }
    return json.dumps(nodes, indent=2)


@mcp.tool(
    name="figma_extract_styles",
    annotations={
        "title": "Extract Styles",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def figma_extract_styles(params: ExtractStylesInput) -> str:
    """Extract design tokens (colors, typography, effects, grids) from a Figma file's published styles.

    Args:
        params (ExtractStylesInput): Input containing:
            - file_key (str): Figma file key
            - types_csv (Optional[str]): Comma-separated style types to filter (FILL, TEXT, EFFECT, GRID)

    Returns:
        str: Formatted text listing colors (with hex values), typography (with size/weight/family),
             effect names, and grid names grouped by category
    """
    file_key, dev_url = resolve(params.file_key)
    raw = get(f"/files/{file_key}/styles")
    styles = raw.get("meta", {}).get("styles", [])
    if params.types_csv:
        types = [t.strip() for t in params.types_csv.split(",")]
        styles = [s for s in styles if s["style_type"] in types]
    if not styles:
        return "no styles defined in this file"

    fills = [s for s in styles if s["style_type"] == "FILL"]
    texts = [s for s in styles if s["style_type"] == "TEXT"]

    colors = [{"name": s["name"]} for s in fills]
    if fills:
        try:
            ids = urllib.parse.quote(",".join(s["node_id"] for s in fills))
            nodes = get(f"/files/{file_key}/nodes?ids={ids}")
            colors = []
            for s in fills:
                doc = (nodes.get("nodes", {}).get(s["node_id"]) or {}).get("document", {})
                f_lst = [f for f in doc.get("fills", []) if f.get("type") == "SOLID" and f.get("visible", True)]
                hex_ = to_hex(f_lst[0]["color"]) if f_lst else "?"
                entry = {"name": s["name"], "hex": hex_}
                if f_lst and f_lst[0].get("opacity", 1) < 1:
                    entry["opacity"] = f_lst[0]["opacity"]
                colors.append(entry)
        except Exception:
            pass

    typography = [{"name": s["name"]} for s in texts]
    if texts:
        try:
            ids = urllib.parse.quote(",".join(s["node_id"] for s in texts))
            nodes = get(f"/files/{file_key}/nodes?ids={ids}")
            typography = []
            for s in texts:
                doc = (nodes.get("nodes", {}).get(s["node_id"]) or {}).get("document", {})
                typo = to_typo(doc.get("style", {}))
                typography.append({"name": s["name"], **typo})
        except Exception:
            pass

    effects = [s["name"] for s in styles if s["style_type"] == "EFFECT"]
    grids = [s["name"] for s in styles if s["style_type"] == "GRID"]

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
                f'{t["size"]}px' if t.get("size") else None,
                f'w{t["weight"]}' if t.get("weight") else None,
                f'lh{t["lh"]}' if t.get("lh") else None,
                t.get("family"),
                t.get("case"),
                f'ls{t["ls"]}' if t.get("ls") else None,
            ]
            lines.append(f'  {t["name"]:<28}  {"  ".join(p for p in parts if p)}')
        lines.append("")
    if effects:
        lines.append("EFFECTS")
        for n in effects:
            lines.append(f"  {n}")
        lines.append("")
    if grids:
        lines.append("GRIDS")
        for n in grids:
            lines.append(f"  {n}")
    return "\n".join(lines).rstrip()


@mcp.tool(
    name="figma_search_components",
    annotations={
        "title": "Search Components",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def figma_search_components(params: SearchComponentsInput) -> str:
    """Search for published components and variant sets in a Figma file.

    Args:
        params (SearchComponentsInput): Input containing:
            - file_key (str): Figma file key
            - query (Optional[str]): Case-insensitive name filter; omit to list all components

    Returns:
        str: Formatted text listing matching variant sets and components with their node IDs,
             names, and descriptions (if any), plus a total count
    """
    file_key, dev_url = resolve(params.file_key)
    results = parallel(f"/files/{file_key}/components", f"/files/{file_key}/component_sets")
    comps = (results[0][0] or {}).get("meta", {}).get("components", [])
    sets = (results[1][0] or {}).get("meta", {}).get("component_sets", [])
    if params.query:
        q = params.query.lower()
        comps = [c for c in comps if q in c["name"].lower()]
        sets = [s for s in sets if q in s["name"].lower()]
    if not comps and not sets:
        return "no components found"

    lines = []
    if sets:
        lines.append("VARIANT SETS")
        for s in sets:
            lines.append(f'  {s["node_id"]:<12}  {s["name"]}')
        lines.append("")
    if comps:
        lines.append("COMPONENTS")
        for c in comps:
            desc = f'  — {c["description"]}' if c.get("description") else ""
            lines.append(f'  {c["node_id"]:<12}  {c["name"]}{desc}')
    lines.append(f'\ntotal: {len(comps) + len(sets)}')
    return "\n".join(lines)


@mcp.tool(
    name="figma_export_images",
    annotations={
        "title": "Export Images",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
async def figma_export_images(params: ExportImagesInput) -> str:
    """Export Figma nodes as images and return their temporary download URLs.

    URLs expire after approximately 30 minutes.

    Args:
        params (ExportImagesInput): Input containing:
            - file_key (str): Figma file key
            - node_ids_csv (str): Comma-separated node IDs to export
            - format (str): Export format — png, jpg, svg, or pdf (default: png)
            - scale (float): Scale multiplier, e.g. 2.0 for @2x (default: 1.0)

    Returns:
        str: Format/scale header followed by node ID and temporary download URL pairs
    """
    ids = urllib.parse.quote(params.node_ids_csv)
    data = get(f"/images/{params.file_key}?ids={ids}&format={params.format}&scale={params.scale}")
    if data.get("err"):
        return f"Error: {data['err']}"
    images = list((data.get("images") or {}).items())
    if not images:
        return "no images returned"
    lines = [f"format:{params.format}  scale:{params.scale}  expires:~30min", ""]
    for id_, url in images:
        lines.append(f"{id_}\n  {url}")
    return "\n".join(lines)


@mcp.tool(
    name="figma_create_design_system_rules",
    annotations={
        "title": "Create Design System Rules",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def figma_create_design_system_rules(params: DesignSystemRulesInput) -> str:
    """Generate a comprehensive design system reference from a Figma file's styles and components.

    Args:
        params (DesignSystemRulesInput): Input containing:
            - file_key (str): Figma file key
            - format (str): Output format — 'text' (default), 'css' (CSS custom properties), or 'markdown'

    Returns:
        str: Design system rules in the requested format, covering colors, typography,
             components, and variant sets
    """
    file_key, dev_url = resolve(params.file_key)
    results = parallel(
        f"/files/{file_key}/styles",
        f"/files/{file_key}/components",
        f"/files/{file_key}/component_sets",
    )
    styles = (results[0][0] or {}).get("meta", {}).get("styles", [])
    comps = (results[1][0] or {}).get("meta", {}).get("components", [])
    sets = (results[2][0] or {}).get("meta", {}).get("component_sets", [])
    fills = [s for s in styles if s["style_type"] == "FILL"]
    texts = [s for s in styles if s["style_type"] == "TEXT"]

    colors = []
    if fills:
        try:
            ids = urllib.parse.quote(",".join(s["node_id"] for s in fills))
            nodes = get(f"/files/{file_key}/nodes?ids={ids}")
            for s in fills:
                doc = (nodes.get("nodes", {}).get(s["node_id"]) or {}).get("document", {})
                f_ = [f for f in doc.get("fills", []) if f.get("type") == "SOLID"]
                colors.append({"name": s["name"], "hex": to_hex(f_[0]["color"]) if f_ else "?"})
        except Exception:
            colors = [{"name": s["name"]} for s in fills]

    typography = []
    if texts:
        try:
            ids = urllib.parse.quote(",".join(s["node_id"] for s in texts))
            nodes = get(f"/files/{file_key}/nodes?ids={ids}")
            for s in texts:
                doc = (nodes.get("nodes", {}).get(s["node_id"]) or {}).get("document", {})
                typo = to_typo(doc.get("style", {}))
                typography.append({"name": s["name"], **typo})
        except Exception:
            typography = [{"name": s["name"]} for s in texts]

    comp_names = [c["name"] for c in comps]
    set_names = [s["name"] for s in sets]

    if params.format == "css":
        lines = [":root {"]
        for c in colors:
            if c.get("hex"):
                tok = c["name"].lower().replace(" ", "-")
                lines.append(f'  --color-{tok}: {c["hex"]};')
        for t in typography:
            tok = t["name"].lower().replace(" ", "-")
            if t.get("size"):   lines.append(f'  --font-size-{tok}: {t["size"]}px;')
            if t.get("weight"): lines.append(f'  --font-weight-{tok}: {t["weight"]};')
            if t.get("lh"):     lines.append(f'  --line-height-{tok}: {t["lh"]}px;')
            if t.get("family"): lines.append(f'  --font-family-{tok}: {t["family"]};')
        lines.append("}")
        return "\n".join(lines)

    if params.format == "markdown":
        lines = ["# Design System\n"]
        if colors:
            lines.append("## Colors")
            for c in colors:
                lines.append(f'- **{c["name"]}** `{c.get("hex", "")}`')
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
            for n in comp_names:
                lines.append(f"- {n}")
        return "\n".join(lines)

    # text (default)
    lines = []
    if colors:
        lines.append("COLORS")
        for c in colors:
            lines.append(f'  {(c.get("hex", "?")):<10}  {c["name"]}')
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
        for n in comp_names:
            lines.append(f"  {n}")
        lines.append("")
    if set_names:
        lines.append("VARIANT SETS")
        for n in set_names:
            lines.append(f"  {n}")
    return "\n".join(lines).rstrip() or "no styles or components found"


@mcp.tool(
    name="figma_generate_design",
    annotations={
        "title": "Generate Figma Design",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def figma_generate_design(params: GenerateDesignInput) -> str:
    """Match a natural-language design spec to existing Figma components and color tokens.

    Suggests a layout pattern, relevant components, and matching color tokens based on
    keyword similarity between the spec and the file's published assets.

    Args:
        params (GenerateDesignInput): Input containing:
            - file_key (str): Figma file key
            - spec (str): Natural language design description (e.g. 'login modal with email field')

    Returns:
        str: Layout suggestion, matched component node IDs/names, matched color tokens,
             and a prompt to use figma_read_nodes for further inspection
    """
    file_key, dev_url = resolve(params.file_key)
    spec = params.spec
    results = parallel(
        f"/files/{file_key}/styles",
        f"/files/{file_key}/components",
        f"/files/{file_key}/component_sets",
    )
    styles = (results[0][0] or {}).get("meta", {}).get("styles", [])
    fills = [s for s in styles if s["style_type"] == "FILL"]
    comps = [(c["node_id"], c["name"]) for c in (results[1][0] or {}).get("meta", {}).get("components", [])]
    sets = [(s["node_id"], s["name"]) for s in (results[2][0] or {}).get("meta", {}).get("component_sets", [])]

    colors = []
    if fills:
        try:
            ids = urllib.parse.quote(",".join(s["node_id"] for s in fills))
            nodes = get(f"/files/{file_key}/nodes?ids={ids}")
            for s in fills:
                doc = (nodes.get("nodes", {}).get(s["node_id"]) or {}).get("document", {})
                f_ = [f for f in doc.get("fills", []) if f.get("type") == "SOLID"]
                colors.append({"name": s["name"], "hex": to_hex(f_[0]["color"]) if f_ else None})
        except Exception:
            colors = [{"name": s["name"]} for s in fills]

    words = [w for w in spec.lower().split() if len(w) > 2]
    score = lambda name: sum(1 for w in words if w in name.lower())
    SEMANTIC = {"primary", "secondary", "background", "surface", "text", "border", "error", "success", "warning"}

    matched_comps = sorted(
        [(id_, n, score(n)) for id_, n in comps + sets if score(n) > 0],
        key=lambda x: -x[2]
    )
    matched_colors = sorted(
        [(c, score(c["name"]) + sum(1 for w in SEMANTIC if w in c["name"].lower())) for c in colors if score(c["name"]) > 0],
        key=lambda x: -x[1]
    )[:5]

    s = spec.lower()
    if "modal" in s or "dialog" in s:   layout = ("overlay", 480, 24)
    elif "card" in s:                    layout = ("card", 360, 16)
    elif "sidebar" in s or "nav" in s:  layout = ("sidebar", 240, 16)
    elif "banner" in s or "hero" in s:  layout = ("banner", "100%", 48)
    elif "form" in s or "login" in s:   layout = ("form", 400, 32)
    elif "list" in s or "table" in s:   layout = ("list", "100%", 16)
    elif "page" in s or "screen" in s:  layout = ("page", 1440, 0)
    else:                                layout = ("frame", 800, 24)

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


@mcp.tool(
    name="figma_get_code_connect_map",
    annotations={
        "title": "Get Code Connect Map",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def figma_get_code_connect_map(params: CodeConnectGetInput) -> str:
    """Look up code-connect mappings that link Figma components to their source code paths.

    Reads from a local `code-connect.json` file in the current working directory.

    Args:
        params (CodeConnectGetInput): Input containing:
            - file_key (str): Figma file key
            - component_id (Optional[str]): Specific component node ID; omit to list all mappings

    Returns:
        str: Mapping details including component name, code file path, and framework identifier
    """
    map_file = os.path.join(os.getcwd(), "code-connect.json")
    try:
        with open(map_file) as f:
            map_ = json.load(f)
    except Exception:
        map_ = {}

    entry = map_.get(params.file_key, {})
    if params.component_id:
        m = entry.get(params.component_id)
        if not m:
            return f"not found: {params.component_id}"
        return (
            f'{params.component_id}  {m["name"]}\n'
            f'  path: {m["codePath"]}\n'
            f'  framework: {m.get("framework", "?")}'
        )
    rows = list(entry.items())
    if not rows:
        return "no mappings for this file"
    lines = [f"code-connect  ({len(rows)} components)", ""]
    for id_, d in rows:
        lines.append(f'{id_:<12}  {d["name"]}')
        lines.append(f'              {d["codePath"]}  [{d.get("framework", "?")}]')
    return "\n".join(lines)


@mcp.tool(
    name="figma_add_code_connect_map",
    annotations={
        "title": "Add Code Connect Map",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def figma_add_code_connect_map(params: CodeConnectAddInput) -> str:
    """Create or update a code-connect mapping linking a Figma component to its source code path.

    Writes to a local `code-connect.json` file in the current working directory.

    Args:
        params (CodeConnectAddInput): Input containing:
            - file_key (str): Figma file key
            - component_id (str): Figma component node ID
            - name (str): Human-readable component name
            - code_path (str): Relative or absolute path to the component's code file
            - framework (Optional[str]): Framework identifier (e.g. 'react', 'vue', 'swift')

    Returns:
        str: Confirmation of whether the mapping was created or updated, with its details
    """
    from datetime import date

    map_file = os.path.join(os.getcwd(), "code-connect.json")
    try:
        with open(map_file) as f:
            map_ = json.load(f)
    except Exception:
        map_ = {}

    if params.file_key not in map_:
        map_[params.file_key] = {}

    existing = map_[params.file_key].get(params.component_id)
    map_[params.file_key][params.component_id] = {
        "name": params.name,
        "codePath": params.code_path,
        "framework": params.framework or (existing or {}).get("framework"),
        "updatedAt": str(date.today()),
    }
    with open(map_file, "w") as f:
        json.dump(map_, f, indent=2)

    action = "updated" if existing else "created"
    return (
        f'{action}  {params.component_id}  {params.name}\n'
        f'  path: {params.code_path}\n'
        f'  framework: {params.framework or "?"}'
    )


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()