#!/usr/bin/env python3
"""
check.py — Validate frontmatter in SKILL.md files.

Usage:
    python3 check.py [directory] [--props prop1 prop2 ...]

Examples:
    python3 check.py ~/.spm/skills
    python3 check.py ~/.spm/skills --props name description keywords
"""

import os
import sys
import argparse

DEFAULT_REQUIRED = ["name", "description"]


def parse_frontmatter(filepath):
    """Extract frontmatter keys from a SKILL.md file."""
    props = {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError) as e:
        return None, f"could not read: {e}"

    if not lines or lines[0].strip() != "---":
        return props, "no frontmatter (does not start with ---)"

    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if ":" in stripped:
            key = stripped.split(":", 1)[0].strip()
            if key:
                props[key] = True

    return props, None


def find_skill_files(root_dir):
    """Find SKILL.md files in top-level skill directories only (matches build_index behaviour)."""
    skill_files = []
    try:
        entries = sorted(os.listdir(root_dir))
    except OSError:
        return []
    for entry in entries:
        if entry.startswith("."):
            continue
        skill_dir = os.path.join(root_dir, entry)
        if not os.path.isdir(skill_dir):
            continue
        skill_md = os.path.join(skill_dir, "SKILL.md")
        if os.path.isfile(skill_md):
            skill_files.append(skill_md)
    return skill_files


def check_skills(root_dir, required_props):
    skill_files = find_skill_files(root_dir)

    if not skill_files:
        print(f"! no SKILL.md files found in: {root_dir}")
        return 1

    print(f"  dir      {os.path.abspath(root_dir)}")
    print(f"  props    {', '.join(required_props)}")
    print(f"  found    {len(skill_files)} files")
    print("-" * 60)

    issues = 0

    for filepath in skill_files:
        props, error = parse_frontmatter(filepath)
        relative = os.path.relpath(filepath, root_dir)

        if error:
            print(f"  x {relative}")
            print(f"    error: {error}")
            issues += 1
            continue

        missing = [p for p in required_props if p not in props]
        if missing:
            print(f"  ! {relative}")
            print(f"    missing: {', '.join(missing)}")
            issues += 1

    print("-" * 60)
    if issues == 0:
        print(f"  + all {len(skill_files)} files OK")
        return 0
    else:
        ok = len(skill_files) - issues
        print(f"  {issues} issue(s)  /  {ok} OK  /  {len(skill_files)} total")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Validate frontmatter properties in SKILL.md files"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Root directory to scan (default: current directory)"
    )
    parser.add_argument(
        "--props",
        nargs="+",
        default=DEFAULT_REQUIRED,
        metavar="PROP",
        help=f"Required properties (default: {' '.join(DEFAULT_REQUIRED)})"
    )

    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(f"  x '{args.directory}' is not a valid directory")
        sys.exit(1)

    sys.exit(check_skills(args.directory, args.props))


if __name__ == "__main__":
    main()