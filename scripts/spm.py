#!/usr/bin/env python3
"""
spm - Skill Package Manager
Usage:
    spm install           Install all skills from skills.json
    spm install <skill>   Install a skill and its dependencies
    spm i                 Alias for install
    spm i <skill>         Alias for install <skill>
    spm remove <skill>    Remove a skill
    spm rm <skill>        Alias for remove
    spm sync              Pull latest skills from remote registry
    spm list              List skills installed in current project
    spm list --global     List all available skills in ~/.skills
    spm search <query>    Search skills by name or description
    spm info <skill>      Show skill frontmatter details
"""

import os
import sys
import json
import shutil
import subprocess
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────

GLOBAL_SKILLS_DIR = os.path.join(os.path.expanduser("~/.spm"), "skills")
SPM_JSON = "skills.json"
PROJECT_ROOT_MARKERS = [".git", "package.json", "pyproject.toml", "Cargo.toml"]


# ── Project root detection ────────────────────────────────────────────────────

def find_project_root():
    """
    Walk up from cwd to find the project root:
    1. First looks for an existing skills.json
    2. Falls back to looking for known project root markers (.git, package.json, etc.)
    3. If nothing found, uses cwd
    Returns the absolute path of the project root.
    """
    current = os.path.abspath(os.getcwd())
    drive = os.path.splitdrive(current)[0] + os.sep  # handles Windows too

    # Pass 1: look for existing skills.json
    path = current
    while True:
        if os.path.isfile(os.path.join(path, SPM_JSON)):
            return path
        parent = os.path.dirname(path)
        if parent == path or path == drive:
            break
        path = parent

    # Pass 2: look for project root markers
    path = current
    while True:
        for marker in PROJECT_ROOT_MARKERS:
            if os.path.exists(os.path.join(path, marker)):
                return path
        parent = os.path.dirname(path)
        if parent == path or path == drive:
            break
        path = parent

    # Fallback: use cwd
    return current


# ── Frontmatter parser ────────────────────────────────────────────────────────

def parse_frontmatter(skill_dir):
    """Parse SKILL.md frontmatter. Returns dict or None."""
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_md):
        return None

    with open(skill_md, "r", encoding="utf-8") as f:
        lines = f.readlines()

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


def get_dependencies(skill_dir):
    """Return list of dependency skill names from frontmatter."""
    fm = parse_frontmatter(skill_dir)
    if not fm or "dependencies" not in fm:
        return []
    raw = fm["dependencies"].strip()
    if not raw:
        return []
    return [d.strip() for d in raw.split() if d.strip()]


# ── .env.example helpers ──────────────────────────────────────────────────────

def parse_env_example(skill_dir):
    """
    Parse .env.example from a skill directory.
    Returns a list of (key, comment) tuples, or an empty list if not found.
    Comment is the inline comment after #, or empty string if none.
    """
    env_example = os.path.join(skill_dir, ".env.example")
    if not os.path.isfile(env_example):
        return []

    entries = []
    with open(env_example, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            # Skip blank lines and pure comment lines
            if not stripped or stripped.startswith("#"):
                continue
            # Split key from inline comment
            if "#" in stripped:
                var_part, _, comment = stripped.partition("#")
                key = var_part.strip().split("=")[0].strip()
                comment = comment.strip()
            else:
                key = stripped.split("=")[0].strip()
                comment = ""
            if key:
                entries.append((key, comment))

    return entries


def notify_env_vars(skill_name, env_vars, root):
    """
    Print a clear notice listing the env vars required by the skill.
    Does NOT write anything to disk — the user handles their .env.
    """
    print(f"\n  ⚠️  '{skill_name}' requires environment variables.")
    print(f"  Add the following to your project's .env:\n")
    for key, comment in env_vars:
        suffix = f"  # {comment}" if comment else ""
        print(f"    {key}={suffix}")
    print()


# ── skills.json helpers ───────────────────────────────────────────────────────

def load_spm_json():
    """Load skills.json from the project root."""
    root = find_project_root()
    spm_path = os.path.join(root, SPM_JSON)
    if not os.path.isfile(spm_path):
        return None, root
    with open(spm_path, "r", encoding="utf-8") as f:
        return json.load(f), root


def save_spm_json(data, root):
    """Save skills.json to the project root."""
    spm_path = os.path.join(root, SPM_JSON)
    with open(spm_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def init_spm_json(root):
    """Create skills.json in the project root if it doesn't exist."""
    spm_path = os.path.join(root, SPM_JSON)
    if not os.path.isfile(spm_path):
        data = {
            "path": ".agents/skills",
            "skills": {}
        }
        save_spm_json(data, root)
        print(f"✅ Created {SPM_JSON} in {root}")
    data, _ = load_spm_json()
    return data


def ensure_gitignore(skills_path, root):
    """Add skills path to .gitignore if not already there."""
    gitignore = os.path.join(root, ".gitignore")
    entry = f"{skills_path}/"

    if os.path.isfile(gitignore):
        with open(gitignore, "r") as f:
            contents = f.read()
        if entry in contents:
            return
        with open(gitignore, "a") as f:
            f.write(f"\n# spm - skill packages\n{entry}\n")
    else:
        with open(gitignore, "w") as f:
            f.write(f"# spm - skill packages\n{entry}\n")

    print(f"📝 Added {entry} to .gitignore")


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_install(skill_name=None):
    """Install a skill and its dependencies, or all skills from skills.json if no name given."""
    root = find_project_root()
    data, _ = load_spm_json()

    if root != os.path.abspath(os.getcwd()):
        print(f"📂 Project root: {root}")

    # No skill name — install all from skills.json (like npm install)
    if skill_name is None:
        if data is None or not data.get("skills"):
            print(f"❌ No {SPM_JSON} found or it has no skills listed.")
            print(f"   Run 'spm install <skill>' to add a skill first.")
            return
        skills_path = data.get("path", ".agents/skills")
        names = list(data["skills"].keys())
        print(f"📦 Installing {len(names)} skill(s) from {SPM_JSON}...\n")
        for name in names:
            _install_skill(name, data, skills_path, required_by=None, root=root)
        ensure_gitignore(skills_path, root)
        save_spm_json(data, root)
        return

    if data is None:
        data = init_spm_json(root)
    skills_path = data.get("path", ".agents/skills")
    _install_skill(skill_name, data, skills_path, required_by=None, root=root)
    ensure_gitignore(skills_path, root)
    save_spm_json(data, root)


def _install_skill(skill_name, data, skills_path, required_by, root):
    """Recursively install a skill and its dependencies."""
    src = os.path.join(GLOBAL_SKILLS_DIR, skill_name)

    if not os.path.isdir(src):
        print(f"❌ Skill '{skill_name}' not found in {GLOBAL_SKILLS_DIR}")
        print(f"   Run 'spm sync' to update the global registry.")
        return False

    # Validate required frontmatter
    fm = parse_frontmatter(src)
    if fm is None:
        print(f"❌ '{skill_name}' has no SKILL.md — skipping")
        return False
    if "name" not in fm or "description" not in fm:
        print(f"⚠️  '{skill_name}' is missing required frontmatter fields (name, description) — skipping")
        return False

    already_installed = skill_name in data["skills"]

    # Install dependencies first
    deps = get_dependencies(src)
    for dep in deps:
        if dep not in data["skills"]:
            print(f"   📦 Installing dependency: {dep}")
            _install_skill(dep, data, skills_path, required_by=skill_name, root=root)
        else:
            # Already installed — make sure required_by is updated
            _add_required_by(data, dep, skill_name)

    # Copy skill to project, excluding .env.example
    dest = os.path.join(root, skills_path, skill_name)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".env.example"))

    # Notify about required env vars (after copy, before summary line)
    env_vars = parse_env_example(src)
    if env_vars:
        notify_env_vars(skill_name, env_vars, root)

    # Update skills.json entry
    entry = data["skills"].get(skill_name, {})
    entry["enabled"] = True
    entry["dependencies"] = deps

    # Track whether this skill requires env vars
    if env_vars:
        entry["env_vars"] = [key for key, _ in env_vars]
    else:
        entry.pop("env_vars", None)

    if required_by:
        rb = entry.get("required_by", [])
        if required_by not in rb:
            rb.append(required_by)
        entry["required_by"] = rb
    elif "required_by" in entry:
        # Explicitly installed — remove required_by if it was there
        del entry["required_by"]

    data["skills"][skill_name] = entry

    if already_installed:
        print(f"🔄 Reinstalled: {skill_name}")
    else:
        print(f"✅ Installed:   {skill_name}")

    return True


def _add_required_by(data, skill_name, requester):
    """Add requester to skill's required_by list."""
    if skill_name not in data["skills"]:
        return
    entry = data["skills"][skill_name]
    rb = entry.get("required_by", [])
    if requester not in rb:
        rb.append(requester)
    entry["required_by"] = rb


def cmd_remove(skill_name):
    """Remove a skill from the project."""
    data, root = load_spm_json()
    if not data:
        print(f"❌ No {SPM_JSON} found. Are you in a project directory?")
        return

    if skill_name not in data["skills"]:
        print(f"❌ Skill '{skill_name}' is not installed in this project.")
        return

    # Check if other skills depend on this one
    dependents = [
        s for s, info in data["skills"].items()
        if skill_name in info.get("dependencies", []) and s != skill_name
    ]
    if dependents:
        print(f"⚠️  Cannot remove '{skill_name}' — required by: {', '.join(dependents)}")
        print(f"   Remove those skills first, or they will break.")
        return

    skills_path = data.get("path", ".agents/skills")
    dest = os.path.join(root, skills_path, skill_name)

    if os.path.exists(dest):
        shutil.rmtree(dest)

    # Clean up required_by references in dependencies
    for dep in data["skills"][skill_name].get("dependencies", []):
        if dep in data["skills"]:
            rb = data["skills"][dep].get("required_by", [])
            if skill_name in rb:
                rb.remove(skill_name)
            if not rb:
                data["skills"][dep].pop("required_by", None)
            else:
                data["skills"][dep]["required_by"] = rb

    del data["skills"][skill_name]
    save_spm_json(data, root)
    print(f"🗑️  Removed: {skill_name}")


def cmd_sync():
    """Pull latest skills from the remote registry."""
    repo_dir = os.path.expanduser("~/.spm")
    if not os.path.isdir(repo_dir):
        print(f"❌ Registry not found: {repo_dir}")
        print(f"   Clone your skills repo there first:")
        print(f"   git clone <your-repo> {repo_dir}")
        return

    print(f"🔄 Syncing {repo_dir} ...")
    result = subprocess.run(
        ["git", "pull"],
        cwd=repo_dir,
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print(f"✅ {result.stdout.strip()}")
    else:
        print(f"❌ Sync failed:\n{result.stderr.strip()}")


def cmd_list(global_flag):
    """List skills — project or global."""
    if global_flag:
        if not os.path.isdir(GLOBAL_SKILLS_DIR):
            print(f"❌ Global skills directory not found: {GLOBAL_SKILLS_DIR}")
            return
        skills = _get_global_skills()
        print(f"📦 Global skills ({len(skills)} available):\n")
        for name in sorted(skills):
            fm = parse_frontmatter(os.path.join(GLOBAL_SKILLS_DIR, name))
            desc = fm.get("description", "No description") if fm else "No description"
            if len(desc) > 60:
                desc = desc[:57] + "..."
            print(f"  {name:<30} {desc}")
    else:
        data, root = load_spm_json()
        if not data or not data.get("skills"):
            print(f"No skills installed. Run 'spm install <skill>'")
            return
        skills = data["skills"]
        print(f"📦 Installed skills ({len(skills)}):\n")
        for name, info in sorted(skills.items()):
            status = "✅" if info.get("enabled") else "⏸️ "
            deps = info.get("dependencies", [])
            dep_str = f"  deps: {', '.join(deps)}" if deps else ""
            rb = info.get("required_by", [])
            rb_str = f"  required_by: {', '.join(rb)}" if rb else ""
            env_str = f"  env: {', '.join(info['env_vars'])}" if info.get("env_vars") else ""
            print(f"  {status} {name}{dep_str}{rb_str}{env_str}")


def cmd_search(query):
    """Search global skills by name or description."""
    if not os.path.isdir(GLOBAL_SKILLS_DIR):
        print(f"❌ Global skills directory not found: {GLOBAL_SKILLS_DIR}")
        return

    query_lower = query.lower()
    results = []

    for skill_name in _get_global_skills():
        fm = parse_frontmatter(os.path.join(GLOBAL_SKILLS_DIR, skill_name))
        if not fm:
            continue
        name = fm.get("name", skill_name)
        desc = fm.get("description", "")
        if query_lower in name.lower() or query_lower in desc.lower():
            results.append((name, desc))

    if not results:
        print(f"🔍 No skills found matching '{query}'")
        return

    print(f"🔍 Results for '{query}' ({len(results)} found):\n")
    for name, desc in sorted(results):
        if len(desc) > 70:
            desc = desc[:67] + "..."
        print(f"  {name:<30} {desc}")


def cmd_info(skill_name):
    """Show frontmatter info for a skill."""
    skill_dir = os.path.join(GLOBAL_SKILLS_DIR, skill_name)
    if not os.path.isdir(skill_dir):
        print(f"❌ Skill '{skill_name}' not found in {GLOBAL_SKILLS_DIR}")
        return

    fm = parse_frontmatter(skill_dir)
    if not fm:
        print(f"❌ No valid SKILL.md found for '{skill_name}'")
        return

    print(f"\n📄 {skill_name}\n{'─' * 40}")
    for key, value in fm.items():
        print(f"  {key:<15} {value}")

    # Show env vars if present
    env_vars = parse_env_example(skill_dir)
    if env_vars:
        print(f"\n  {'env vars':<15}")
        for key, comment in env_vars:
            suffix = f"  # {comment}" if comment else ""
            print(f"    {key}{suffix}")

    # List files in skill dir (excluding .env.example — it's internal)
    files = []
    for root, dirs, filenames in os.walk(skill_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in filenames:
            if f == ".env.example":
                continue
            rel = os.path.relpath(os.path.join(root, f), skill_dir)
            files.append(rel)

    print(f"\n  {'files':<15} {len(files)}")
    for f in sorted(files):
        print(f"    • {f}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_global_skills():
    """Return list of skill names in the global directory."""
    return [
        d for d in os.listdir(GLOBAL_SKILLS_DIR)
        if os.path.isdir(os.path.join(GLOBAL_SKILLS_DIR, d))
        and not d.startswith(".")
        and os.path.isfile(os.path.join(GLOBAL_SKILLS_DIR, d, "SKILL.md"))
    ]


# ── CLI ───────────────────────────────────────────────────────────────────────

HELP = """
  spm — Skill Package Manager

  Usage:  spm <command> [args]

  Commands:
    install               Install all skills from skills.json
    install <skill>       Install a skill and its dependencies
    i / i <skill>         Alias for install
    remove <skill>        Remove a skill from the project
    rm <skill>            Alias for remove
    sync                  Pull latest skills from remote registry
    list                  List skills installed in current project
    list --global         List all available skills in ~/.skills
    search <query>        Search skills by name or description
    info <skill>          Show skill details

  Examples:
    spm i figma-mcp
    spm remove figma-mcp
    spm search frontend
    spm list --global
    spm sync
"""

def print_help():
    print(HELP)


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print_help()
        return

    command = args[0]

    if command in ("install", "i"):
        cmd_install(args[1] if len(args) > 1 else None)

    elif command in ("remove", "rm"):
        if len(args) < 2:
            print("Usage: spm remove <skill>")
            return
        cmd_remove(args[1])

    elif command == "sync":
        cmd_sync()

    elif command == "list":
        global_flag = "--global" in args
        cmd_list(global_flag)

    elif command == "search":
        if len(args) < 2:
            print("Usage: spm search <query>")
            return
        cmd_search(" ".join(args[1:]))

    elif command == "info":
        if len(args) < 2:
            print("Usage: spm info <skill>")
            return
        cmd_info(args[1])

    else:
        print(f"Unknown command: '{command}'")
        print_help()


if __name__ == "__main__":
    main()