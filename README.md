![br<ai>n cover](assets/cover.png)

# Brain

A registry of reusable skills for AI coding agents — Claude, Gemini, Cursor, Copilot, and others — with a token-efficient MCP server for runtime access, and a CLI for registry management.

Each skill is a folder with a `SKILL.md` that tells the agent how to approach a specific task — what tools to use, what patterns to follow, what to watch out for.

**One standard format. Any model. Any IDE.**

---

## How it works

Skills live in `~/.brain/skills/`. Agents access them at runtime through an MCP server (`mcp.py`) using progressive disclosure — fetching only what they need, when they need it, without loading entire files into context.

The CLI (`brain`) handles registry management: syncing from remote and searching for skills.

```
~/.brain/
├── mcp.py              ← MCP server (agent access layer)
├── index.json              ← pre-built frontmatter index
├── skills/                 ← all available skills
│   ├── frontend-design/
│   │   └── SKILL.md
│   └── ...
└── scripts/
    └── build_index.py      ← called by brain sync to regenerate index.json
```

---

## Setup

### 1. Clone the registry

```bash
git clone https://github.com/Raulvalverdeleal/brain ~/.brain
```

### 2. Install `brain`

`brain` is the CLI for registry management. Make it available globally:

```bash
echo 'alias brain="python3 ~/.brain/scripts/brain.py"' >> ~/.zshrc
source ~/.zshrc
```

### 3. Build the index

```bash
brain build-index
```

This parses all skill frontmatters once and writes `~/.brain/index.json`. The MCP server loads this file at startup instead of scanning hundreds of files — startup goes from seconds to milliseconds.


> `brain` requires Python 3. No dependencies beyond the standard library.

### 4. Register the MCP server

Add to your MCP config (e.g. `opencode.json`):

```json
{
  "mcp": {
    "brain": {
      "command": "python3",
      "args": ["~/.brain/brain_mcp.py"]
    }
  }
}
```

The server auto-installs its only dependency (`mcp[cli]`) on first run.

---

## CLI reference

```
brain sync                       Pull registry and rebuild index if changed
brain search <query> [--page N]  Search skills  (prefix terms with - to exclude)
brain info   <skill>             Show metadata and file tree for a skill
brain list                       List all skills in the registry
```

**Examples:**

```bash
brain sync
brain search "react state management"
brain search frontend -azure --page 2
brain info   react-best-practices
brain list
```

### sync

Runs `git pull`. If changes are detected — or if `index.json` is missing — it rebuilds the index automatically. If the registry is already current, it prints index stats and exits.

```
● Syncing ~/.brain ...
✓ Already up to date.
──────────────────────────────────────────────────
   index    2025-01-05T10:22:11Z  943 skills
   no changes — index up to date
```

### search

Scores skills against your query and returns ranked results (5 per page). Name matches score highest, then keywords, then description. Use `-term` to exclude noisy results.

```bash
brain search "react state"
brain search postgres -azure -cloud
brain search "api design" --page 2
```

### info

Shows full metadata for a skill: description, keywords, dependencies, file tree.

```bash
brain info postgres-best-practices
```

---

## MCP server tools

The MCP server exposes seven tools for progressive skill access. Agents move through levels only as deep as needed — **a typical session costs ~400 tokens vs 2000+** loading a full skill file cold.

```
skill_search    → find candidates (paginated, ranked)
skill_info      → frontmatter + file tree, zero content cost
skill_toc       → heading tree only, up to 5 skills at once
skill_section   → one section by slug
skill_get       → full SKILL.md content
skill_get_file  → any supporting file (references/, scripts/)
skill_index_status → health check, force reload after sync
```

### Progressive disclosure flow

```
agent: skill_search("figma design implementation")
→ 3 results, page 1 of 2

agent: skill_info("figma-implement-design")
→ frontmatter + file tree (no content loaded)

agent: skill_toc("figma-implement-design")
→ heading tree with slugs, dependency TOCs appended

agent: skill_section("figma-implement-design", "phase-3-design-tokens")
→ only that section
```

### skill_search

Paginated search across all 900+ skills. Supports negative filtering.

```
query: "figma design"  matches:4  page:1/2

→ call skill_search(query='figma design', page=2) for more

■ figma-implement-design  (score:14)
  Full workflow to go from a Figma file to production-ready code...
```

### skill_toc

Returns the heading tree of one or more skills as addressable slugs. Pass up to 5 IDs in one call to plan your section fetches upfront.

```
■ figma-implement-design

#phase-1-orient  Phase 1 — Orient
#phase-2-visual-reference  Phase 2 — Visual reference
  #phase-3-design-tokens  Phase 3 — Design tokens
  ...

supporting files:
  references/advanced-patterns.md
```

Dependency TOCs are listed but not expanded automatically — the agent requests them explicitly if needed.

### skill_section

Fetches content from one heading to the next heading of equal or higher level. The primary efficiency tool — use it instead of `skill_get` whenever possible.

```bash
skill_section("figma-implement-design", "phase-3-design-tokens")
```

### skill_info

Returns frontmatter metadata and file tree with zero content cost. If a `skills.json` exists in the project with `notes` for this skill, they are appended automatically.

---

## How skills work

When the agent receives a task, it uses `skill_search` to find relevant skills, then progressively loads content via `skill_toc` and `skill_section`. The agent fetches `skill_get` only when it needs the full document.

Skills are intentionally independent — you only load what your task needs.

### Skill structure

```
skills/
└── your-skill-name/
    ├── SKILL.md          ← required
    ├── .env.example      ← optional: declares required env vars (BRAIN_ prefix)
    ├── references/       ← optional: supplementary docs
    └── scripts/          ← optional: helper scripts
```

### Required frontmatter

Every `SKILL.md` must start with a YAML frontmatter block:

```yaml
---
name: your-skill-name
description: One or two sentences. When should an agent use this skill?
dependencies: other-skill another-skill
keywords: react ui components typescript
---
```

`name` and `description` are required. `dependencies` and `keywords` are optional but improve search ranking and dependency resolution.

### index.json

`index.json` is generated by `build_index.py` and is the MCP server's data source. It contains parsed frontmatter for every skill — never full content. Rebuild it after any `brain sync` that pulls changes.

```json
{
  "_meta": {
    "built_at": "2025-01-05T10:22:11Z",
    "skill_count": 943
  },
  "skills": {
    "frontend-design": {
      "name": "frontend-design",
      "description": "...",
      "keywords": ["react", "ui", "css"],
      "dependencies": [],
      "file_tree": ["SKILL.md"],
      "has_references": false,
      "has_scripts": false
    }
  }
}
```

---

## Contributing

**1 PR = 1 skill.** Keep PRs focused — one new skill or one update to an existing one.

### Checklist before opening a PR

- [ ] Folder is inside `skills/` and the name matches `name` in frontmatter
- [ ] `name` and `description` are present in frontmatter
- [ ] `keywords` are present (improves MCP search ranking)
- [ ] `dependencies` lists any skills this one relies on
- [ ] If the skill needs env vars: `.env.example` exists with `BRAIN_`-prefixed names
- [ ] `SKILL.md` gives the agent enough context to act without guessing
- [ ] No unrelated files included

### Writing a good `SKILL.md`

- **Be prescriptive.** Tell the agent exactly what to do, not just what the skill is about.
- **Cover edge cases.** What should the agent watch out for? What are common mistakes?
- **Use headings.** The MCP server exposes skills section by section — well-structured headings make partial loading much more useful.
- **Reference, don't duplicate.** If content belongs in `references/` or `scripts/`, put it there and link from `SKILL.md`.
- **Keep it focused.** One skill = one responsibility. If it's doing two things, split it.

### Environment variables

If your skill needs secrets or config, include a `.env.example`:

```bash
BRAIN_YOUR_TOKEN=    # your personal access token
BRAIN_YOUR_ORG=      # your organization slug
```

All variable names must be prefixed with `BRAIN_`. The `.env.example` file is read by `build_index.py` to surface setup notices — it is never copied anywhere.

---

## Available skills

Over 900 skills across categories including AI agents, frontend, backend, cloud, security, databases, testing, and more. Use the CLI or MCP server to browse:

```bash
<<<<<<< Updated upstream
spm list                    # all skills
spm search "your topic"     # ranked search
spm info <skill>            # details for one skill
```
=======
brain list                    # all skills
brain search "your topic"     # ranked search
brain info <skill>            # details for one skill
```
>>>>>>> Stashed changes
