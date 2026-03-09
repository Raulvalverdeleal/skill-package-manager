# Skill Package Manager

A collection of ready-to-use skills for AI coding agents (Claude, Gemini, Cursor, Copilot, and others), with a built-in package manager to install and manage them per project.

Each skill is a folder with a `SKILL.md` that tells the agent how to approach a specific task — what tools to use, what patterns to follow, what to watch out for.

**One standard format. Any model. Any IDE. Shared across your whole team.**

Skills live in your project under `.agents/skills/` — tracked in `skills.json`, ignored by git. Everyone on the team installs the same skills, the agent always finds them in the same place, regardless of whether they're using Claude, Gemini, Cursor, or Copilot.

---

## How to use

### 1. Clone the registry

```bash
git clone https://github.com/Raulvalverdeleal/skill-package-manager ~/.spm
```

This is your local registry. All available skills live in `~/.spm/skills/`.

### 2. Install `spm`

`spm` is the CLI that copies skills into your projects. Since it's already in the cloned repo, just make it available globally — pick whichever approach you prefer:

**Option A — symlink** (recommended):
```bash
ln -s ~/.spm/scripts/spm.py /usr/local/bin/spm
chmod +x /usr/local/bin/spm
```

**Option B — shell alias**:
```bash
echo 'alias spm="python3 ~/.spm/scripts/spm.py"' >> ~/.zshrc
source ~/.zshrc
```

> **Note:** `spm` requires Python 3. No dependencies beyond the standard library.

### 3. Install skills into a project

```bash
cd your-project

spm install figma-mcp       # installs the skill + its dependencies
spm i figma-mcp             # same, shorter
```

This copies the skill into `.agents/skills/` at your project root, creates a `skills.json` for traceability, and adds `.agents/skills/` to `.gitignore` automatically.

`spm` detects the project root automatically — you can run it from any subdirectory and it will always install to the right place.

#### Environment variables

Some skills require API tokens or other secrets. When a skill includes a `.env.example`, `spm` will print the required variables during install:

```
⚠️  'figma-mcp' requires environment variables.
Add the following to your project's .env:

    SPM_FIGMA_TOKEN=   # your Figma personal access token
```

The `.env.example` is never copied into your project — only the notice is shown. Add the variables to your `.env` manually before using the skill. All skill-owned variables are prefixed with `SPM_` to avoid conflicts.

### 4. Share with your team

Commit `skills.json` to your repo. Your teammates run:

```bash
spm install   # installs all skills listed in skills.json — like npm install
```

### 5. Keep the registry up to date

```bash
spm sync    # runs git pull in ~/.spm
```

### All commands

```
spm install               Install all skills from skills.json
spm install <skill>       Install a skill and its dependencies
spm i / spm i <skill>     Alias for install
spm remove <skill>        Remove a skill from the project
spm rm <skill>            Alias for remove
spm sync                  Pull latest skills from remote registry
spm list                  List skills installed in current project
spm list --global         List all available skills in ~/.spm
spm search <query>        Search skills by name or description
spm info <skill>          Show skill details
```

---

## Available skills

Over 500 skills across categories including AI agents, frontend, backend, cloud, security, databases, testing, and more. Some highlights:

| Skill | Description |
|---|---|
| `figma-implement-design` | Takes a Figma file and builds the full app — tokens, UI kit, pixel-faithful layout |
| `figma-mcp` | Read and inspect Figma files via MCP |
| `frontend-design` | Production-grade frontend interfaces with high design quality |
| `react-best-practices` | Curated React performance and patterns rules |
| `postgres-best-practices` | Postgres query, schema, and connection best practices |
| `sentry-mcp` | Fetch and triage Sentry issues directly from the agent |
| `loki-mode` | Autonomous agent mode for complex multi-step tasks |
| `mcp-builder` | Build and evaluate MCP servers |

Run `spm list --global` to see everything available after cloning.

---

## How skills work

When the agent receives a task, the `AGENTS.md` instructs it to:

1. Read `skills.json` for a quick index of installed skills and their metadata
2. Run `ls .agents/skills/` to confirm what's available
3. `grep` for skills relevant to the task
4. Read the matching `SKILL.md` files before writing any code
5. Proceed with its own judgment if no relevant skill is found

Skills are intentionally project-local — you only include what your project needs, and the folder can safely live in `.gitignore`.

### skills.json

`skills.json` is the source of truth for what's installed. Beyond tracking skill names and dependencies, it supports a `notes` field per skill — a place for the agent to accumulate project-specific context across sessions:

```json
{
  "path": ".agents/skills",
  "skills": {
    "figma-mcp": {
      "enabled": true,
      "dependencies": [],
      "env_vars": ["SPM_FIGMA_TOKEN"],
      "notes": [
        "main design system file key: aBcDeFgH",
        "user prefers SVGs inlined, not saved to assets/",
        "export URLs expire fast — run export and wget in the same command"
      ]
    }
  }
}
```

Notes are written by the agent when it discovers something worth remembering: stack details, errors it has solved, user preferences, project-specific gotchas. They are read at the start of every session to avoid repeating reasoning.

---

## Repo structure

```
skill-package-manager/
├── scripts/
│   ├── spm.py        ← skill package manager CLI
│   └── check.py      ← validates skill frontmatter
├── skills/           ← all available skills
│   ├── figma-mcp/
│   │   ├── SKILL.md
│   │   └── .env.example   ← optional: declares required env vars
│   ├── frontend-design/
│   │   └── SKILL.md
│   └── ...
└── AGENTS.md         ← paste into your project to enable skill discovery
```

---

## Contributing

**1 PR = 1 skill.** Keep PRs focused — one new skill or one update to an existing one.

### Required structure

```
skills/
└── your-skill-name/
    ├── SKILL.md          ← required
    ├── .env.example      ← required if the skill needs env vars
    ├── references/       ← optional: extra docs the agent may need
    └── scripts/          ← optional: helper scripts referenced from SKILL.md
```

### Required frontmatter

Every `SKILL.md` must start with a YAML frontmatter block:

```yaml
---
name: your-skill-name
description: One or two sentences. When should an agent use this skill? Be specific.
dependencies: other-skill another-skill   # space-separated, omit if none
---
```

`name` and `description` are required. `dependencies` is optional but must be accurate — `spm` uses it to resolve installs.

### Environment variables

If your skill needs secrets or config, include a `.env.example` at the skill root:

```bash
SPM_YOUR_TOKEN=    # description of what this is and where to get it
SPM_YOUR_ORG=      # e.g. your organization slug
```

- All variable names must be prefixed with `SPM_`
- The `.env.example` is never copied into the user's project — `spm` reads it only to display the setup notice
- The skill's script must load only the variables declared in its own `ENV_VARS` list, never the full `.env`

### Writing a good `SKILL.md`

- **Be prescriptive.** Tell the agent exactly what to do, not just what the skill is about.
- **Cover edge cases.** What should the agent watch out for? What are common mistakes?
- **Reference, don't duplicate.** If a script or doc belongs in `scripts/` or `references/`, put it there and link to it from `SKILL.md`.
- **Keep it focused.** One skill = one responsibility. If it's doing two things, split it.

### Checklist before opening a PR

- [ ] Folder is inside `skills/` and the name matches `name` in frontmatter
- [ ] `name` and `description` are present in frontmatter
- [ ] `dependencies` lists any skills this one relies on
- [ ] If the skill needs env vars: `.env.example` exists with `SPM_`-prefixed names
- [ ] `SKILL.md` gives the agent enough context to act without guessing
- [ ] No unrelated files included