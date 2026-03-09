---
name: sentry-mcp
description: Interact with the Sentry API to list, inspect, resolve, and archive production issues.
depencencies: 
---

# SKILL — sentry

## Usage
```bash
python .agents/skills/sentry-mcp/scripts/sentry_api.py <command> [args]
python .agents/skills/sentry-mcp/scripts/sentry_api.py list_tools
```
## Commands

### `discover`
Lists all projects under your token. Use to find `SENTRY_ORG` and `SENTRY_PROJECT`.

### `list_issues [limit] [cursor]`
Top unresolved issues sorted by frequency. Default limit: 20.  
If there are more results, output includes a `next cursor` — pass it as second arg to paginate.

Key fields: `shortId`, `title`, `culprit` (crash origin), `count`, `userCount`, `priority`, `firstSeen/lastSeen`.

### `get_issue_details <issue_id>`
Full issue with latest event: stack trace (last 5 frames), last 8 breadcrumbs, user, env, release.

Reading the stack: frames are innermost-last — the last frame matching your codebase (not node_modules) is the crash site.  
Reading breadcrumbs: read chronologically, focus on the last `http`/`navigation` entries before the crash.

### `resolve_issue <issue_id>`
Marks issue as resolved. Call after fix is committed and verified.

### `ignore_issue <issue_id>`
Archives issue permanently — hidden from unresolved list.  
⚠️ Always confirm with the user before running this.

## Errors

| Code | Cause |
|---|---|
| 401 | Token invalid or expired |
| 403 | Token lacks permission |
| 404 | Wrong issue_id, org, or project |