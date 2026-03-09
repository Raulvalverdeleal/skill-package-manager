---
name: sentry-fix-issue
description: Full workflow to fix a single Sentry issue: branch check, triage report, fix, review, and commit. Use when the user provides a Sentry issue ID and wants to resolve it end-to-end.
dependencies: sentry-mcp systematic-debugging
---

## Step 1 — Branch check

```bash
git branch --show-current
```

If the current branch is not `fix/sentry`, stop and tell the user:

```
⚠️  Switch to fix/sentry before continuing:
    git checkout fix/sentry
    # or
    git checkout -b fix/sentry
```

Do not proceed until confirmed.

---

## Step 2 — Fetch issue

```bash
python scripts/sentry_api.py get_issue_details <issue_id>
```

---

## Step 3 — Triage report

Present a concise report before proposing anything:

```
ISSUE   <shortId>  <title>
──────────────────────────────────────────────
Severity    <critical|high|medium|low>  (<count> events, <userCount> users)
Crash site  <filename>:<lineNo>  <function>
Root cause  <one sentence>
Active      first <firstSeen>  →  last <lastSeen>
Env         <environment>  release <release>
```

**Severity mapping:**
- `critical` — >1000 events or >100 users or P0 priority
- `high`     — >100 events or >10 users or P1
- `medium`   — P2 or first seen <48h
- `low`      — everything else

Wait for user acknowledgement before proceeding.

---

## Step 4 — Fix

Locate the crash site in the codebase. Read the function. Apply the minimal fix that addresses the root cause — not a catch wrapper.

Follow `systematic-debugging` for root cause analysis if the origin is indirect.

Show the diff to the user and wait for approval before writing any file.

---

## Step 5 — Review

After applying:
1. Search the codebase for the same pattern — fix all instances
2. Run existing tests for the affected file if any
3. Confirm no regressions

---

## Step 6 — Commit + resolve

```bash
git add <changed_files>
git commit -m "fix(<scope>): <what was wrong and how it was fixed>

Fixes <shortId> — <issue_title>
Events: <count>  Users: <userCount>"
```

Then resolve in Sentry — only after user confirms the fix is good:

```bash
python scripts/sentry_api.py resolve_issue <issue_id>
```

---

## Hard rules

- Never skip Step 1 — wrong branch = no work done
- Never resolve without explicit user confirmation
- Never wrap in try/catch as the sole fix
- If root cause is unclear after reading the stack, ask — don't guess