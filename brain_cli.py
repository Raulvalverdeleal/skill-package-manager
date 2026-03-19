#!/usr/bin/env python3
"""
brain — Skill Package Manager CLI
Commands: sync, search, info, list
"""

import os
import sys
import json
import re
import subprocess

# ── Config ────────────────────────────────────────────────────────────────────

BRAIN_DIR     = os.path.expanduser("~/.brain")
AGENTS_DIR = os.path.expanduser("~/.agents")
SKILLS_DIR  = os.path.join(AGENTS_DIR, "skills")
INDEX_PATH  = os.path.join(BRAIN_DIR, "index.json")
BUILD_INDEX = os.path.join(BRAIN_DIR, "scripts", "build_index.py")
CHECK       = os.path.join(BRAIN_DIR, "scripts", "check.py")

# ── ANSI colors ───────────────────────────────────────────────────────────────

_NO_COLOR = not sys.stdout.isatty() or bool(os.environ.get("NO_COLOR"))

def _c(code: str, text: str) -> str:
    return text if _NO_COLOR else f"\033[{code}m{text}\033[0m"

def green(t):  return _c("32", t)
def red(t):    return _c("31", t)
def yellow(t): return _c("33", t)
def cyan(t):   return _c("36", t)
def bold(t):   return _c("1",  t)
def dim(t):    return _c("2",  t)

OK   = green("✓")
FAIL = red("✗")
WARN = yellow("!")
BULL = cyan("●")
DASH = dim("─")

# ── Index helpers ─────────────────────────────────────────────────────────────

def _load_index() -> tuple[dict, dict]:
    if not os.path.isfile(INDEX_PATH):
        return {}, {"error": f"index not found at {INDEX_PATH}"}
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return raw.get("skills", {}), raw.get("_meta", {})
    except Exception as e:
        return {}, {"error": str(e)}

def _index_ok() -> bool:
    _, meta = _load_index()
    return "error" not in meta

# ── Frontmatter parser (fallback when index missing) ─────────────────────────

def _parse_frontmatter(skill_dir: str) -> dict:
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_md):
        return {}
    try:
        with open(skill_md, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    data = {}
    for line in lines[1:]:
        s = line.strip()
        if s == "---":
            break
        if ":" in s:
            k, _, v = s.partition(":")
            data[k.strip()] = v.strip()
    return data

# ── Scoring ───────────────────────────────────────────────────────────────────

def _parse_query(query: str) -> tuple[list, list]:
    tokens, negatives = [], []
    for part in query.lower().split():
        if part.startswith("-") and len(part) > 1:
            negatives.append(part[1:])
        else:
            tokens.append(part)
    return tokens, negatives

def _score(entry: dict, tokens: list, negatives: list) -> int:
    name = entry.get("name", "").lower()
    desc = entry.get("description", "").lower()
    kws  = [k.lower() for k in entry.get("keywords", [])]
    deps = [d.lower() for d in entry.get("dependencies", [])]

    for neg in negatives:
        if neg in name or neg in desc or any(neg in k for k in kws):
            return -1

    score = 0
    for tok in tokens:
        if tok == name:                              score += 10
        if tok in name.split("-"):                   score += 4
        if any(tok == k  for k in kws):              score += 5
        if any(tok in k  for k in kws):              score += 2
        if tok in name:                              score += 3
        if tok in re.findall(r'\w+', desc):          score += 1
        if tok in desc:                              score += 1
        if any(tok in d  for d in deps):             score += 1
    return score

# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_sync():
    if not os.path.isdir(BRAIN_DIR):
        print(f"{FAIL} Registry not found: {BRAIN_DIR}")
        print(f"   Clone first:  git clone <repo> {BRAIN_DIR}")
        sys.exit(1)

    print(f"{BULL} Syncing {dim(BRAIN_DIR)} ...")

    result = subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=BRAIN_DIR, capture_output=True, text=True,
    )

    if result.returncode != 0:
        print(f"{FAIL} git pull failed\n{red(result.stderr.strip())}")
        sys.exit(1)

    out = result.stdout.strip()
    already_current = "Already up to date" in out or "Already up-to-date" in out

    if already_current:
        print(f"{OK} {dim(out)}")
        if _index_ok():
            skills, meta = _load_index()
            print(f"{dim(DASH * 50)}")
            print(f"   index    {dim(meta.get('built_at', '?'))}  "
                  f"{cyan(str(meta.get('skill_count', len(skills))))} skills")
            print(f"   {dim('no changes — index up to date')}")
            return
        print(f"{WARN} index missing — building ...")
    else:
        print(f"{OK} {out}")
        print(f"{BULL} Changes detected — rebuilding index ...")

    _run_build_index()

def _run_build_index():
    if not os.path.isfile(BUILD_INDEX):
        print(f"{FAIL} build_index.py not found at {BUILD_INDEX}")
        sys.exit(1)

    result = subprocess.run(
        [sys.executable, BUILD_INDEX],
        capture_output=True, text=True,
    )

    if result.returncode != 0:
        print(f"{FAIL} build_index failed\n{red(result.stderr.strip())}")
        sys.exit(1)

    for line in result.stderr.splitlines():
        if "indexed" in line:
            # Strip the "[build_index] " prefix
            msg = re.sub(r'^\[build_index\]\s*', '', line.strip())
            print(f"{OK} {msg}")
            break
    else:
        print(f"{OK} index rebuilt")

    skills, meta = _load_index()
    print(f"{dim(DASH * 50)}")
    print(f"   index    {dim(meta.get('built_at', '?'))}  "
          f"{cyan(str(meta.get('skill_count', len(skills))))} skills")

def cmd_search(query: str, page: int = 1):
    skills, meta = _load_index()
    if not skills:
        print(f"{FAIL} {meta.get('error', 'index empty')}")
        print(f"   Run:  brain sync")
        sys.exit(1)

    tokens, negatives = _parse_query(query)
    if not tokens:
        print(f"{FAIL} empty query after negatives")
        sys.exit(1)

    scored = []
    for sid, entry in skills.items():
        s = _score(entry, tokens, negatives)
        if s > 0:
            scored.append((s, sid, entry))
    scored.sort(key=lambda x: (-x[0], x[1]))

    PAGE_SIZE = 5
    total = len(scored)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page  = max(1, min(page, pages))
    start = (page - 1) * PAGE_SIZE
    chunk = scored[start : start + PAGE_SIZE]

    print(f"\n{bold('search')}  {dim(query)}  "
          f"{cyan(str(total))} match{'es' if total != 1 else ''}  "
          f"page {page}/{pages}")
    print(dim(DASH * 60))

    if not chunk:
        print(f"  {dim('no results — try broader terms')}")
        return

    for score_val, sid, entry in chunk:
        desc = entry.get("description", "")
        if len(desc) > 110:
            desc = desc[:107].rsplit(" ", 1)[0] + "..."
        kws    = entry.get("keywords", [])
        kw_s   = f"  {dim('[' + ', '.join(kws[:4]) + ']')}" if kws else ""
        deps   = entry.get("dependencies", [])
        dep_s  = f"\n     {dim('deps: ' + ', '.join(deps))}" if deps else ""
        flags  = ""
        if entry.get("has_references"): flags += green(" r")
        if entry.get("has_scripts"):    flags += green(" s")

        print(f"\n  {BULL} {bold(sid)}{flags}{kw_s}")
        print(f"     {desc}{dep_s}")

    print(f"\n{dim(DASH * 60)}")
    hints = []
    if page < pages:
        hints.append(f"brain search {query} --page {page + 1}  ({pages - page} more page(s))")
    hints.append("brain info <skill>  for full details")
    for h in hints:
        print(f"  {dim(h)}")
    print()

def cmd_info(skill_id: str):
    skills, _ = _load_index()
    entry = skills.get(skill_id) if skills else None

    if entry is None and os.path.isdir(os.path.join(SKILLS_DIR, skill_id)):
        fm = _parse_frontmatter(os.path.join(SKILLS_DIR, skill_id))
        if fm:
            entry = fm

    if entry is None:
        close = [s for s in skills if skill_id in s][:4] if skills else []
        hint  = f"\n  Did you mean: {', '.join(close)}" if close else ""
        print(f"{FAIL} Skill not found: {bold(skill_id)}{hint}")
        sys.exit(1)

    print(f"\n{bold(skill_id)}")
    print(dim(DASH * 60))
    print(f"  {entry.get('description', dim('no description'))}")
    print()

    rows = []
    if entry.get("keywords"):
        rows.append(("keywords",     ", ".join(entry["keywords"])))
    if entry.get("dependencies"):
        rows.append(("dependencies", ", ".join(entry["dependencies"])))
    if entry.get("has_references"):
        rows.append(("references",   green("yes")))
    if entry.get("has_scripts"):
        rows.append(("scripts",      green("yes")))
    for k, v in (entry.get("meta") or {}).items():
        rows.append((k, str(v)))

    if rows:
        width = max(len(r[0]) for r in rows) + 2
        for k, v in rows:
            print(f"  {dim(k.ljust(width))}{v}")
        print()

    file_tree = entry.get("file_tree", [])
    if file_tree:
        print(f"  {dim('files')}")
        for p in file_tree:
            print(f"    {dim('○')} {p}")
        print()

    print(dim(DASH * 60))
    print(f"  {dim('brain search <query>  to find related skills')}\n")

def cmd_list():
    skills, meta = _load_index()

    if not skills:
        if os.path.isdir(SKILLS_DIR):
            names = sorted(
                d for d in os.listdir(SKILLS_DIR)
                if os.path.isdir(os.path.join(SKILLS_DIR, d)) and not d.startswith(".")
            )
            print(f"\n{bold('registry')}  {dim('(index missing — run brain sync)')}")
            print(dim(DASH * 60))
            for name in names:
                print(f"  {dim('○')} {name}")
            print(f"\n  {cyan(str(len(names)))} skills on disk\n")
        else:
            print(f"{FAIL} Registry not found. Run: git clone <repo> {BRAIN_DIR}")
        return

    built = meta.get("built_at", "?")
    count = meta.get("skill_count", len(skills))

    print(f"\n{bold('registry')}  {dim(built)}  {cyan(str(count))} skills")
    print(dim(DASH * 60))

    for sid in sorted(skills):
        e    = skills[sid]
        r    = green("r") if e.get("has_references") else dim("·")
        s    = green("s") if e.get("has_scripts")    else dim("·")
        deps = len(e.get("dependencies", []))
        d    = cyan(f"d:{deps}") if deps else dim("   ")
        print(f"  {dim('○')} {sid:<44} {d}  {r}{s}")

    print(f"\n  {dim('r=references  s=scripts  d:N=dependencies')}")
    print(f"  {dim('brain info <skill>  for details')}\n")


def cmd_check(props: list | None = None):
    """Validate frontmatter in all SKILL.md files."""
    if not os.path.isfile(CHECK):
        print(f"{FAIL} check.py not found at {CHECK}")
        sys.exit(1)

    argv = [sys.executable, CHECK, SKILLS_DIR]
    if props:
        argv += ["--props"] + props

    result = subprocess.run(argv, text=True)
    sys.exit(result.returncode)

# ── CLI entry point ───────────────────────────────────────────────────────────

HELP = f"""
  {bold('brain')} — Skill Package Manager

  {dim('Usage:')}  brain <command> [args]

  {dim('Commands:')}
    sync                       Pull registry and rebuild index if changed
    build-index                Rebuild index.json from skills on disk
    check [--props p1 p2 ...]   Validate frontmatter in all SKILL.md files
    search <query> [--page N]  Search skills  (prefix with - to exclude)
    info   <skill>             Show metadata and file tree for a skill
    list                       List all skills in the registry

  {dim('Examples:')}
    brain sync
    brain build-index
    brain check
    brain check --props name description keywords
    brain search "react state management"
    brain search frontend -azure --page 2
    brain info   react-best-practices
    brain list
"""

def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(HELP)
        return

    cmd  = args[0]
    rest = args[1:]

    if cmd == "sync":
        cmd_sync()

    elif cmd == "build-index":
        print(f"{BULL} Building index ...")
        _run_build_index()

    elif cmd == "check":
        props = rest if rest and rest[0] != "--props" else None
        if "--props" in rest:
            idx = rest.index("--props")
            props = rest[idx + 1:] or None
        cmd_check(props)

    elif cmd == "search":
        if not rest:
            print(f"{FAIL} Usage: brain search <query> [--page N]")
            sys.exit(1)
        page, parts, i = 1, [], 0
        while i < len(rest):
            if rest[i] in ("--page", "-p") and i + 1 < len(rest):
                try:
                    page = int(rest[i + 1])
                except ValueError:
                    print(f"{FAIL} --page must be a number")
                    sys.exit(1)
                i += 2
            else:
                parts.append(rest[i])
                i += 1
        cmd_search(" ".join(parts), page=page)

    elif cmd == "info":
        if not rest:
            print(f"{FAIL} Usage: brain info <skill>")
            sys.exit(1)
        cmd_info(rest[0])

    elif cmd == "list":
        cmd_list()

    else:
        print(f"{FAIL} Unknown command: {bold(cmd)}")
        print(HELP)
        sys.exit(1)

if __name__ == "__main__":
    main()