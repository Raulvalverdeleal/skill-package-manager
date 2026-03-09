---
name: node-generate-test
description: Auto generate test for your changes by identifying the changed code.
---

# Testing Workflow

## 0. Bootstrap (run once)

Read the project config from `skills.json`:

```bash
cat skills.json
```

Look for the `node-generate-test` entry and read its `notes` field:

```json
"node-generate-test": {
  "notes": {
    "test_folder": "...",
    "file_naming": "...",
    "mock_database": "...",
    "mock_policy": "..."
  }
}
```

For each variable missing or not yet set, ask the user:

| Variable | Question |
|---|---|
| `test_folder` | Where are your test files located? (e.g. `test/`, `__tests__/`, `src/**/*.spec.ts`) |
| `file_naming` | What naming convention do test files use? (`camelCase`, `kebab-case`, `snake_case`) |
| `mock_database` | Should the database be mocked? (`true` = mock / `false` = use real DB) |
| `mock_policy` | Besides the database, what else should be mocked? (e.g. "only external APIs and third-party services") |

Once answered, write the values into `skills.json` under `node-generate-test.notes`:

```json
"node-generate-test": {
  "enabled": true,
  "dependencies": [],
  "notes": {
    "test_folder": "test/",
    "file_naming": "kebab-case",
    "mock_database": "true",
    "mock_policy": "only external APIs and third-party services"
  }
}
```

Do not ask again in future runs — the values are already in `skills.json`.

---

## 1. Identify changed code

Get the current branch:

```bash
git branch --show-current
```

If the branch **is not** `main`, compare against main:

```bash
git diff main...HEAD
git diff main...HEAD --name-only
```

If the branch **is** `main`, get the commits not yet pushed:

```bash
git diff origin/main..HEAD
git diff origin/main..HEAD --name-only
```

Also check for uncommitted changes:

```bash
git status
git diff
```

Note the affected functions, classes, routes, and middlewares.

---

## 2. Analyze impact

For each changed file, trace:
- Which routes or middlewares are affected.
- Which service/controller/util functions are involved.
- Whether the change affects input validation, auth, DB access, or external calls.

---

## 3. Locate existing tests

Search in `test_folder`:

```bash
grep -r "functionName\|keyword" <test_folder>
grep -r "routePath" <test_folder>
grep -r "describe\|it(" <test_folder> | grep "keyword"
```

Map each changed unit to its test file. If a test file exists, read it fully before writing anything new.

---

## 4. Decide whether to create a test

Create a test if any of these apply:
- The changed function has business logic, validation, or error handling.
- It's a route handler (any HTTP method).
- It handles auth, permissions, or sensitive data.
- The bug/feature is non-trivial.

Skip if the change is purely cosmetic (formatting, renaming with no logic change).

---

## 5. Create the test

Before writing anything, read `test_folder` to understand the conventions — syntax, structure, helpers, setup/teardown, and assertion style. Match them exactly.

File naming: use the `file_naming` convention from `skills.json`.

**File creation policy:**
If a test file for the same topic already exists, append the new test at the end of that file. Do not create a new file.

**Mocking policy:**
- Database: use `mock_database` value from `skills.json`
- Everything else: follow `mock_policy` from `skills.json`

**Coverage rules by test type:**

- **Unit** — one function in isolation. Cover: happy path, edge cases, invalid inputs, thrown errors.
- **Integration** — route → controller → service → DB. Cover: valid flow, validation errors, not found, auth failures.
- **E2E** — full HTTP cycle against the real app. Cover: status codes, response headers, response body shape.

---

## 6. Run the test

```bash
npm test
node <test_folder>/my-test.js   # single file
```

---

## 7. Debug the test

If the test fails:
- Read the assertion error — compare actual vs expected.
- Verify the DB state before the operation (setup/teardown).
- Check that async flows are properly awaited.
- Use `console.log` or `node --inspect` only if the error isn't obvious.
- If the test itself is wrong, fix it first and justify why before touching source code.