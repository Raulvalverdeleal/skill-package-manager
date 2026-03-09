---
name: sentry-fix-batch
description: Fetch the N most critical Sentry issues and process each one using sentry-fix-issue. Triage each issue and decide whether to fix, ignore, or archive before acting. N defaults to 5.
dependencies: sentry-mcp sentry-fix-issue
---

# sentry-fix-batch

> Each issue is processed using `sentry-fix-issue`.  
> This skill only adds the batch loop, ranking, and triage decision gate.

---

## Step 1 — Branch check
Must be on `fix/sentry` branch  before anything else.

---

## Step 2 — Fetch issues

```bash
python scripts/sentry_api.py list_issues <n>   # default 5
```
Present the ranked list before doing anything:

```
#  shortId          severity   impact   users   events  title
1  PROJ-123         critical   4320     432     0       TypeError: ...
2  PROJ-89          high       310      28      30      Cannot read ...
3  PROJ-44          medium     80       7       10      Unhandled rejection ...
```
---

## Step 3 — Process each issue

For each issue:

### 3a. Run the triage report

Follow `sentry-fix-issue` Steps 2 and 3 to fetch details and produce the report.

### 3b. Decide action

After showing the report, ask the user to choose:

```
[F] Fix      — apply fix, commit, resolve in Sentry
[I] Ignore   — skip for now, move to next
[A] Archive  — ignore_issue in Sentry (use for third-party errors, known noise)
```

**Suggest the action** based on these signals — the user makes the final call:

| Signal | Suggested action |
|---|---|
| Crash site in `node_modules`, SDK, or third-party lib | Archive |
| Error title contains vendor name (Cookiebot, Clarity, HotJar…) | Archive |
| `firstSeen` > 30 days ago, low and stable event count | Archive |
| High userCount or recent spike | Fix |
| Already fixed in a recent release | Resolve without changes |

### 3c. Execute

**Fix** → follow `sentry-fix-issue` Steps 4–6 fully for this issue, then continue to next.

**Ignore** → skip, note it in the session summary, continue.

**Archive** →
```bash
python scripts/sentry_api.py ignore_issue <issue_id>
```
Confirm with user first, then continue.

---

## Step 4 — Session commit (fixes only)

If two or more issues were fixed in the same files, squash into one commit:

```bash
git add <all_changed_files>
git commit -m "fix(sentry): resolve batch of <n> issues

- fix <shortId>: <one-line description>
- fix <shortId>: <one-line description>
..."
```

If each fix touched different files, they were already committed individually in Step 3c — nothing to do here.

---

## Step 5 — Session summary

Print a summary table when all issues are processed:

```
BATCH SUMMARY  (<n> issues processed)
──────────────────────────────────────
shortId       action    title
PROJ-123      fixed     TypeError: cannot read 'id' of undefined
PROJ-89       archived  Cookiebot consent error
PROJ-44       ignored   —
```

---

## Hard rules

- Never process the next issue before the current one is fully resolved or skipped
- Never archive without explicit user confirmation — always show the reason
- Never fix more than one issue in a single file edit — commit each fix atomically before moving on