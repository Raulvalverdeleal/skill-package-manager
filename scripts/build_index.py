#!/usr/bin/env python3
"""
build_index.py — Pre-build ~/.brain/index.json from all skill frontmatters.
"""

import os
import sys
import json
import time
import datetime

BRAIN_DIR = os.path.expanduser("~/.brain")
AGENTS_DIR = os.path.expanduser("~/.agents")
SKILLS_DIR = os.path.join(AGENTS_DIR, "skills")
INDEX_PATH = os.path.join(BRAIN_DIR, "index.json")

# ── Frontmatter parser ────────────────────────────────────────────────────────

def parse_frontmatter(skill_dir: str) -> dict | None:
    """Parse SKILL.md YAML frontmatter. Returns dict or None if missing/invalid."""
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_md):
        return None

    try:
        with open(skill_md, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None

    if not lines or lines[0].strip() != "---":
        return {}

    data = {}
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            data[key.strip()] = value.strip()

    return data


def parse_list_field(raw: str) -> list[str]:
    """Parse a space-separated frontmatter field into a list."""
    if not raw:
        return []
    return [item.strip() for item in raw.split() if item.strip()]


# ── File tree builder ─────────────────────────────────────────────────────────

def build_file_tree(skill_dir: str) -> list[str]:
    """Return relative paths of all files in the skill directory."""
    tree = []
    for root, dirs, files in os.walk(skill_dir):
        # Skip hidden dirs
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for fname in sorted(files):
            if fname == ".env.example":
                continue
            abs_path = os.path.join(root, fname)
            rel = os.path.relpath(abs_path, skill_dir)
            tree.append(rel)
    return tree


# ── Index builder ─────────────────────────────────────────────────────────────

def build_index(skills_dir: str) -> dict:
    """Walk skills directory, parse frontmatters, return full index."""
    if not os.path.isdir(skills_dir):
        print(f"[build_index] skills dir not found: {skills_dir}", file=sys.stderr)
        return {}

    skill_dirs = sorted(
        d for d in os.listdir(skills_dir)
        if os.path.isdir(os.path.join(skills_dir, d)) and not d.startswith(".")
    )

    index = {}
    skipped = 0
    total = len(skill_dirs)

    for skill_name in skill_dirs:
        skill_dir = os.path.join(skills_dir, skill_name)
        fm = parse_frontmatter(skill_dir)

        if fm is None:
            skipped += 1
            print(f"[build_index] skipped (no SKILL.md): {skill_name}", file=sys.stderr)
            continue  # No SKILL.md at all

        file_tree = build_file_tree(skill_dir)
        subdirs = {os.path.dirname(p) for p in file_tree if os.path.dirname(p)}

        entry = {
            "name":         fm.get("name", skill_name),
            "description":  fm.get("description", ""),
            "keywords":     parse_list_field(fm.get("keywords", "")),
            "dependencies": parse_list_field(fm.get("dependencies", "")),
            "file_tree":    file_tree,
            "has_references": "references" in subdirs,
            "has_scripts":    "scripts"    in subdirs,
        }

        # Carry any extra frontmatter fields (e.g. license, version, author)
        known = {"name", "description", "keywords", "dependencies"}
        extra = {k: v for k, v in fm.items() if k not in known and v}
        if extra:
            entry["meta"] = extra

        index[skill_name] = entry

    print(
        f"[build_index] indexed {len(index)} skills  "
        f"(skipped {skipped}, total dirs {total})",
        file=sys.stderr
    )
    return index


def main():
    t0 = time.time()
    print(f"[build_index] scanning {SKILLS_DIR} ...", file=sys.stderr)
    index = build_index(SKILLS_DIR)

    output = {
        "_meta": {
            "built_at":    datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "skill_count": len(index),
            "brain_dir":     BRAIN_DIR,
        },
        "skills": index,
    }

    os.makedirs(BRAIN_DIR, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - t0
    print(
        f"[build_index] wrote {INDEX_PATH}  "
        f"({len(index)} skills, {elapsed:.2f}s)",
        file=sys.stderr
    )


if __name__ == "__main__":
    main()