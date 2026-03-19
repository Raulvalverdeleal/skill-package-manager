#!/usr/bin/env python3
"""
brain_mcp.py — BRAIN MCP Server
Progressive skill access: search → info → toc → section → full skill
Place at ~/.brain/brain_mcp.py and register in your MCP config.
Requires ~/.brain/index.json (run build_index.py first, or brain sync).
"""

import subprocess
import sys


def _ensure_deps():
    required = ["mcp[cli]"]
    missing = []
    for pkg in required:
        import_name = pkg.split("[")[0].replace("-", "_")
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[brain_mcp] installing: {' '.join(missing)}", file=sys.stderr)
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--break-system-packages"] + missing
        )


_ensure_deps()

import os
import re
import json
import time
from typing import Optional
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict

# ── Constants ─────────────────────────────────────────────────────────────────

BRAIN_DIR  = os.path.expanduser("~/.brain")
AGENTS_DIR = os.path.expanduser("~/.agents")
SKILLS_DIR = os.path.join(AGENTS_DIR, "skills")
INDEX_PATH = os.path.join(BRAIN_DIR, "index.json")

PAGE_SIZE = 3       # skills per search page
MAX_DESC  = 160     # chars shown in search results

# ── Index ─────────────────────────────────────────────────────────────────────

_INDEX: dict = {}        # skill_id → entry
_INDEX_META: dict = {}   # _meta block
_INDEX_LOADED_AT: float = 0.0


def _load_index(force: bool = False) -> None:
    global _INDEX, _INDEX_META, _INDEX_LOADED_AT
    if _INDEX and not force:
        return
    if not os.path.isfile(INDEX_PATH):
        _INDEX = {}
        _INDEX_META = {"error": f"index.json not found at {INDEX_PATH} — run build_index.py"}
        return
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        _INDEX      = raw.get("skills", {})
        _INDEX_META = raw.get("_meta", {})
        _INDEX_LOADED_AT = time.time()
    except Exception as e:
        _INDEX = {}
        _INDEX_META = {"error": str(e)}


def _skill_dir(skill_id: str) -> str:
    return os.path.join(SKILLS_DIR, skill_id)


def _skill_md(skill_id: str) -> str:
    return os.path.join(_skill_dir(skill_id), "SKILL.md")


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score(entry: dict, tokens: list[str], negatives: list[str]) -> int:
    name  = entry.get("name",        "").lower()
    desc  = entry.get("description", "").lower()
    kws   = [k.lower() for k in entry.get("keywords", [])]
    deps  = [d.lower() for d in entry.get("dependencies", [])]

    # Negative filter — any hit disqualifies
    for neg in negatives:
        if neg in name or neg in desc or neg in kws:
            return -1

    score = 0
    for tok in tokens:
        if tok == name:
            score += 10
        if tok in name.split("-"):
            score += 4
        for kw in kws:
            if tok == kw:
                score += 5
            elif tok in kw:
                score += 2
        if tok in name:
            score += 3
        words = re.findall(r'\w+', desc)
        if tok in words:
            score += 1
        if tok in desc:
            score += 1
        for dep in deps:
            if tok in dep:
                score += 1

    return score


def _parse_query(query: str) -> tuple[list[str], list[str]]:
    """Split 'react -azure -security' → (['react'], ['azure', 'security'])."""
    tokens, negatives = [], []
    for part in query.lower().split():
        if part.startswith("-") and len(part) > 1:
            negatives.append(part[1:])
        else:
            tokens.append(part)
    return tokens, negatives


# ── TOC helpers ───────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')


def _parse_headings(content: str) -> list[dict]:
    """Return list of {level, text, slug, line_index} for every heading."""
    headings = []
    lines = content.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r'^(#{1,6})\s+(.*)', line)
        if m:
            level = len(m.group(1))
            text  = m.group(2).strip()
            headings.append({
                "level":      level,
                "text":       text,
                "slug":       _slugify(text),
                "line_index": i,
            })
    return headings


def _render_toc(headings: list[dict]) -> str:
    lines = []
    for h in headings:
        indent = "  " * (h["level"] - 1)
        lines.append(f'{indent}#{h["slug"]}  {h["text"]}')
    return "\n".join(lines)


def _extract_section(content: str, slug: str) -> str | None:
    """Extract content from the heading matching slug to the next same-or-higher heading."""
    headings = _parse_headings(content)
    target = next((h for h in headings if h["slug"] == slug), None)
    if not target:
        return None

    lines = content.splitlines()
    start = target["line_index"]
    level = target["level"]

    # Find end: next heading at same or higher level
    end = len(lines)
    for h in headings:
        if h["line_index"] > start and h["level"] <= level:
            end = h["line_index"]
            break

    return "\n".join(lines[start:end]).strip()


# ── Notes injection ───────────────────────────────────────────────────────────

def _get_notes(skill_id: str) -> list[str]:
    """Read project notes for a skill from skills.json in cwd, if present."""
    try:
        p = os.path.join(os.getcwd(), "skills.json")
        if not os.path.isfile(p):
            return []
        with open(p) as f:
            data = json.load(f)
        return data.get("skills", {}).get(skill_id, {}).get("notes", [])
    except Exception:
        return []


# ── Related skills ────────────────────────────────────────────────────────────

def _get_related(skill_id: str, limit: int = 3) -> list[str]:
    """Return skill IDs related via dependencies or name similarity."""
    _load_index()
    entry = _INDEX.get(skill_id, {})
    related = set()

    # Direct dependencies
    for dep in entry.get("dependencies", []):
        if dep in _INDEX:
            related.add(dep)

    # Skills that depend on this one
    for sid, e in _INDEX.items():
        if skill_id in e.get("dependencies", []) and sid != skill_id:
            related.add(sid)

    # Name-similarity fallback if we don't have enough
    if len(related) < limit:
        name_parts = set(skill_id.replace("-", " ").split())
        for sid, e in _INDEX.items():
            if sid == skill_id or sid in related:
                continue
            other_parts = set(sid.replace("-", " ").split())
            if name_parts & other_parts:
                related.add(sid)
            if len(related) >= limit * 2:
                break

    return sorted(related)[:limit]


# ── MCP Server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "brain",
    instructions="Before starting any task, search for relevant skills using skill_search. Use skill_toc and skill_section to load only what you need."
)


# ── Input models ─────────────────────────────────────────────────────────────

class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str  = Field(..., description=(
        "Search terms, space-separated. Prefix with - to exclude: 'react -azure'. "
        "Scores name matches highest, then keywords, then description."
    ))
    page: int   = Field(default=1, ge=1, description="Result page (3 skills per page)")


class SkillIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id: str = Field(..., description="Exact skill identifier, e.g. 'frontend-design'")


class MultiSkillTocInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_ids: list[str] = Field(..., description="One or more skill IDs to get TOC for", min_length=1, max_length=5)


class SectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id:     str = Field(..., description="Skill identifier")
    section_slug: str = Field(..., description="Section slug from skill_toc, e.g. 'phase-3-design-tokens'")


class FileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id:      str = Field(..., description="Skill identifier")
    relative_path: str = Field(..., description="File path relative to skill dir, e.g. 'references/patterns.md'")


class IndexStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reload: bool = Field(default=False, description="Force reload index from disk")


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool(name="skill_search")
async def skill_search(params: SearchInput) -> str:
    """Search skills by name, keywords, and description.

    Returns 3 results per page ranked by relevance. Each result shows name and
    description only — call skill_info once you find a candidate you want to
    inspect further. Use negative terms (e.g. '-azure') to filter out noise.

    Flow: skill_search → skill_info → skill_toc → skill_section / skill_get
    """
    _load_index()

    if not _INDEX:
        err = _INDEX_META.get("error", "index empty")
        return f"error: {err}\nRun: python3 ~/.brain/scripts/build_index.py"

    tokens, negatives = _parse_query(params.query)
    if not tokens:
        return "error: query is empty after removing negatives"

    scored = []
    for skill_id, entry in _INDEX.items():
        s = _score(entry, tokens, negatives)
        if s > 0:
            scored.append((s, skill_id, entry))

    scored.sort(key=lambda x: -x[0])

    total   = len(scored)
    pages   = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page    = min(params.page, pages)
    start   = (page - 1) * PAGE_SIZE
    results = scored[start : start + PAGE_SIZE]

    if not results:
        return f'no results for "{params.query}"'

    lines = [f'{total} matches  page {page}/{pages}', ""]
    if page < pages:
        lines.append(f"next: page={page+1}")
        lines.append("")

    for _, skill_id, entry in results:
        desc = entry.get("description", "")
        if len(desc) > MAX_DESC:
            desc = desc[:MAX_DESC].rsplit(" ", 1)[0] + "…"
        lines.append(skill_id)
        lines.append(f"  {desc}")
        lines.append("")

    return "\n".join(lines).rstrip()


@mcp.tool(name="skill_info")
async def skill_info(params: SkillIdInput) -> str:
    """Get full metadata for a skill: frontmatter, file tree, dependencies, and project notes.

    No content is loaded — zero content-token cost. Use this to confirm a skill
    is the right one before fetching its content via skill_toc or skill_get.
    """
    _load_index()
    entry = _INDEX.get(params.skill_id)
    if not entry:
        close = [sid for sid in _INDEX if params.skill_id in sid][:3]
        hint  = f"\nDid you mean: {', '.join(close)}" if close else ""
        return f"skill not found: {params.skill_id}{hint}"

    lines = [
        f"■ {entry['name']}",
        f"  {entry.get('description', '')}",
        "",
    ]

    if entry.get("keywords"):
        lines.append(f"keywords:     {', '.join(entry['keywords'])}")
    if entry.get("dependencies"):
        lines.append(f"dependencies: {', '.join(entry['dependencies'])}")

    meta = entry.get("meta", {})
    for k, v in meta.items():
        if k not in {"name", "description", "keywords", "dependencies"}:
            lines.append(f"{k:<14}{v}")

    lines.append("")
    lines.append(f"has_references: {entry.get('has_references', False)}")
    lines.append(f"has_scripts:    {entry.get('has_scripts', False)}")

    file_tree = entry.get("file_tree", [])
    if file_tree:
        lines.append("\nfiles:")
        for f in file_tree:
            lines.append(f"  {f}")

    related = _get_related(params.skill_id)
    if related:
        lines.append(f"\nrelated: {', '.join(related)}")

    notes = _get_notes(params.skill_id)
    if notes:
        lines.append("\nproject notes:")
        for note in notes:
            lines.append(f"  · {note}")

    lines.append(f"\n→ call skill_toc('{params.skill_id}') to see section structure")
    return "\n".join(lines)


@mcp.tool(name="skill_toc")
async def skill_toc(params: MultiSkillTocInput) -> str:
    """Get the table of contents (heading tree) for one or more skills.

    Returns heading slugs you can pass to skill_section to fetch only the
    content you need. Also lists supporting files from references/ and scripts/.
    Dependency TOCs are appended automatically if the skill declares them.

    Pass up to 5 skill IDs to get a merged TOC in one call.
    """
    _load_index()
    blocks = []

    for skill_id in params.skill_ids:
        entry = _INDEX.get(skill_id)
        if not entry:
            blocks.append(f"[{skill_id}] not found in index")
            continue

        skill_md_path = _skill_md(skill_id)
        if not os.path.isfile(skill_md_path):
            blocks.append(f"[{skill_id}] SKILL.md not on disk — run: brain install {skill_id}")
            continue

        with open(skill_md_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        # Strip frontmatter
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                content = content[end + 3:].lstrip()

        headings = _parse_headings(content)
        toc      = _render_toc(headings)

        block = [f"■ {skill_id}", ""]
        if toc:
            block.append(toc)
        else:
            block.append("(no headings)")

        # Supporting files
        file_tree = entry.get("file_tree", [])
        support   = [p for p in file_tree if p != "SKILL.md"]
        if support:
            block.append("\nsupporting files:")
            for p in support:
                block.append(f"  {p}")

        # Dependency TOCs — collapsed summary
        deps = entry.get("dependencies", [])
        if deps:
            block.append(f"\ndependencies: {', '.join(deps)}")
            block.append("→ call skill_toc with dependency IDs to expand them")

        block.append(f"\n→ call skill_section('{skill_id}', '<slug>') for a section")
        block.append(f"→ call skill_get('{skill_id}') for the full skill")
        blocks.append("\n".join(block))

    return "\n\n" + ("\n\n---\n\n".join(blocks)) + "\n"


@mcp.tool(name="skill_section")
async def skill_section(params: SectionInput) -> str:
    """Fetch a single section of a skill by its heading slug.

    The most token-efficient way to read skill content — fetch only what you
    need. Get slugs from skill_toc first.

    Example: skill_section('figma-implement-design', 'phase-3-design-tokens')
    """
    skill_md_path = _skill_md(params.skill_id)
    if not os.path.isfile(skill_md_path):
        return f"SKILL.md not found for '{params.skill_id}' — run: brain install {params.skill_id}"

    with open(skill_md_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Strip frontmatter
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:].lstrip()

    section = _extract_section(content, params.section_slug)
    if section is None:
        headings = _parse_headings(content)
        available = "\n".join(f"  #{h['slug']}  {h['text']}" for h in headings)
        return (
            f"section '{params.section_slug}' not found in {params.skill_id}\n\n"
            f"available sections:\n{available}"
        )

    notes = _get_notes(params.skill_id)
    footer = ""
    if notes:
        footer = "\n\n---\nproject notes:\n" + "\n".join(f"· {n}" for n in notes)

    return f"[{params.skill_id}#{params.section_slug}]\n\n{section}{footer}"


@mcp.tool(name="skill_get")
async def skill_get(params: SkillIdInput) -> str:
    """Fetch the full SKILL.md content for a skill.

    Use this only when you need the entire skill. For most tasks,
    skill_toc + skill_section is more token-efficient.
    Frontmatter is stripped (already available via skill_info).
    Project notes are appended if present.
    """
    skill_md_path = _skill_md(params.skill_id)
    if not os.path.isfile(skill_md_path):
        return f"SKILL.md not found for '{params.skill_id}' — run: brain install {params.skill_id}"

    with open(skill_md_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Strip frontmatter
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:].lstrip()

    notes = _get_notes(params.skill_id)
    footer = ""
    if notes:
        footer = "\n\n---\nproject notes:\n" + "\n".join(f"· {n}" for n in notes)

    related = _get_related(params.skill_id)
    rel_str = f"\nrelated: {', '.join(related)}" if related else ""

    return f"[{params.skill_id}]\n\n{content}{footer}{rel_str}"


@mcp.tool(name="skill_get_file")
async def skill_get_file(params: FileInput) -> str:
    """Fetch any supporting file from a skill directory (references, scripts, etc.).

    Use skill_info to discover available files in the file_tree.
    Example: skill_get_file('figma-implement-design', 'references/patterns.md')
    """
    # Safety: prevent path traversal
    skill_dir  = os.path.realpath(_skill_dir(params.skill_id))
    target     = os.path.realpath(os.path.join(skill_dir, params.relative_path))

    if not target.startswith(skill_dir + os.sep) and target != skill_dir:
        return f"error: path traversal not allowed"

    if not os.path.isfile(target):
        entry = _INDEX.get(params.skill_id, {})
        tree  = entry.get("file_tree", [])
        hint  = "\navailable files:\n" + "\n".join(f"  {p}" for p in tree) if tree else ""
        return f"file not found: {params.relative_path} in {params.skill_id}{hint}"

    with open(target, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


@mcp.tool(name="skill_index_status")
async def skill_index_status(params: IndexStatusInput) -> str:
    """Check index status: skill count, build date, and optionally reload from disk.

    Use reload=true if you've just run brain sync and want fresh data.
    """
    _load_index(force=params.reload)

    if not _INDEX:
        err = _INDEX_META.get("error", "index empty")
        return f"index not loaded: {err}\nRun: python3 ~/.brain/scripts/build_index.py"

    built_at = _INDEX_META.get("built_at", "unknown")
    count    = _INDEX_META.get("skill_count", len(_INDEX))
    brain_dir  = _INDEX_META.get("brain_dir", BRAIN_DIR)

    lines = [
        f"index: OK",
        f"skills:    {count}",
        f"built_at:  {built_at}",
        f"brain_dir:   {brain_dir}",
        f"index:     {INDEX_PATH}",
    ]

    if _INDEX_LOADED_AT:
        age = int(time.time() - _INDEX_LOADED_AT)
        lines.append(f"in_memory: {age}s ago")

    if params.reload:
        lines.append("(reloaded from disk)")

    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Eagerly load index on startup so first tool call is fast
    _load_index()
    count = len(_INDEX)
    err   = _INDEX_META.get("error")
    if err:
        print(f"[brain_mcp] warning: {err}", file=sys.stderr)
    else:
        print(f"[brain_mcp] index loaded — {count} skills", file=sys.stderr)
    mcp.run()