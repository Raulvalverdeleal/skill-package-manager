## Skills

Project skills are located in `.agents/skills/`.
The full list of installed skills and their metadata is in `skills.json` at the project root — check it first for a quick index before hitting the filesystem.

### Before starting any task

1. **Check the skill index:**
```bash
   cat skills.json
```
   This gives you the installed skills, their dependencies, and required env vars at a glance.
   Also read any `notes` entries — they contain project-specific context accumulated from previous sessions.

2. **List available skills:**
```bash
   ls .agents/skills/
```

3. **Search for skills relevant to your task:**
```bash
   ls .agents/skills/ | grep -i "keyword"
```
   Try multiple terms if the first search returns nothing (e.g. `auth`, `clerk`, `jwt`, `login`).

4. **Read the SKILL.md files that apply:**
```bash
   cat .agents/skills/skill-name/SKILL.md
```
   If a SKILL.md references additional files (playbooks, scripts, references), read those too.

5. **If no relevant skill exists**, proceed with your own judgment. Do not block the task.

### During and after a task

When you discover something worth remembering for future sessions, write it into the `notes` array of the relevant skill in `skills.json`:

- Stack or environment details (e.g. "project uses React 19 with Vite, not Next.js")
- Errors encountered and how they were resolved (e.g. "HTTP 403 on figma_export_images was caused by missing quotes in .env — strip them")
- User decisions and preferences (e.g. "user prefers archive over ignore for third-party Sentry errors")
- Gotchas specific to this project that the SKILL.md doesn't cover
```json
"figma-mcp": {
  "enabled": true,
  "dependencies": [],
  "env_vars": ["SPM_FIGMA_TOKEN"],
  "notes": [
    "file key for the main design system: aBcDeFgH",
    "export URLs consistently expire before download — run export and wget in the same command",
    "user wants SVGs inlined, not saved to assets/"
  ]
}
```

Notes are append-only — never delete an existing note, only add.

### Notes

- A task may require combining multiple skills (e.g. implementation + testing + deployment).
- Prefer the more specific skill over a generic one when both apply.
- Reading an extra SKILL.md costs little; missing a relevant one can cost a lot.
- If a skill lists `env_vars` in `skills.json`, verify those variables are set in `.env` before running any script from that skill.
- If you found a path 