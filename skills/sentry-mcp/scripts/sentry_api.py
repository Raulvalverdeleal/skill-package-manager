#!/usr/bin/env python3
"""
sentry_api.py — Sentry API tool runner
Config read from SENTRY_TOKEN, SENTRY_ORG, SENTRY_PROJECT environment variables.
Base URL is hardcoded to https://de.sentry.io/api/0

Usage:
  python sentry_api.py <tool> [args...]

Tools:
  list_tools
  discover
  list_issues                [limit] [cursor]
  get_issue_details          <issue_id>
  resolve_issue              <issue_id>
  ignore_issue               <issue_id>
"""
import os, sys, json, urllib.request, urllib.parse, urllib.error
from pathlib import Path

# ── Env ───────────────────────────────────────────────────────────────────────

ENV_VARS = ["SPM_SENTRY_TOKEN", "SPM_SENTRY_ORG", "SPM_SENTRY_PROJECT"]

def _find_project_root():
    """Walk up from cwd to find the project root (where .env lives)."""
    current = os.path.abspath(os.getcwd())
    drive = os.path.splitdrive(current)[0] + os.sep

    # Pass 1: skills.json
    path = current
    while True:
        if os.path.isfile(os.path.join(path, "skills.json")):
            return path
        parent = os.path.dirname(path)
        if parent == path or path == drive:
            break
        path = parent

    # Pass 2: common project root markers
    path = current
    while True:
        for marker in (".git", "package.json", "pyproject.toml", "Cargo.toml"):
            if os.path.exists(os.path.join(path, marker)):
                return path
        parent = os.path.dirname(path)
        if parent == path or path == drive:
            break
        path = parent

    return current


def _load_env():
    env_file = Path(_find_project_root()) / ".env"
    if not env_file.exists():
        return
    declared = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            declared[k.strip()] = v.strip().strip('"').strip("'")
    for key in ENV_VARS:
        if key in declared:
            os.environ.setdefault(key, declared[key])

_load_env()

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = "https://de.sentry.io/api/0"

def _cfg():
    token   = os.environ.get("SPM_SENTRY_TOKEN", "")
    org     = os.environ.get("SPM_SENTRY_ORG", "")
    project = os.environ.get("SPM_SENTRY_PROJECT", "")
    missing = [k for k, v in [
        ("SPM_SENTRY_TOKEN", token),
        ("SPM_SENTRY_ORG", org),
        ("SPM_SENTRY_PROJECT", project),
    ] if not v]
    if missing:
        sys.exit(f"Error: missing environment variables: {', '.join(missing)}")
    return token, org, project, BASE_URL

# ── HTTP ──────────────────────────────────────────────────────────────────────

def get(url):
    token, *_ = _cfg()
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), dict(r.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise Exception(f"HTTP {e.code} {e.reason}: {body}")

def put(url, body):
    token, *_ = _cfg()
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="PUT", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise Exception(f"HTTP {e.code} {e.reason}: {body}")

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_link_header(header):
    if not header: return {}
    links = {}
    for part in header.split(","):
        sections = part.split(";")
        if len(sections) < 2: continue
        url      = sections[0].strip().strip("<>")
        name     = sections[1].strip()
        results  = len(sections) > 2 and sections[2].strip() == 'results="true"'
        cursor   = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("cursor", [None])[0]
        if 'rel="next"' in name: links["next"] = {"cursor": cursor, "results": results}
        if 'rel="prev"' in name: links["prev"] = {"cursor": cursor, "results": results}
    return links

# ── Tools ─────────────────────────────────────────────────────────────────────

def tool_list_tools():
    return __doc__.strip()

def tool_discover():
    _, org, _, base_url = _cfg()
    data, _ = get(f"{base_url}/projects/")
    lines = ["PROJECTS"]
    for p in data:
        lines.append(f'  {p["organization"]["slug"]}/{p["slug"]:<24}  {p["platform"] or "?"}  {p["name"]}')
    return "\n".join(lines)

def tool_list_issues(limit=20, cursor=""):
    _, org, project, base_url = _cfg()
    url = f"{base_url}/projects/{org}/{project}/issues/?query=is:unresolved&sort=freq&limit={limit}"
    if cursor: url += f"&cursor={cursor}"
    data, headers = get(url)
    pagination = parse_link_header(headers.get("Link"))

    lines = [f"ISSUES  (showing {len(data)}, sorted by frequency)"]
    if pagination.get("next", {}).get("results"):
        lines.append(f'next cursor: {pagination["next"]["cursor"]}')
    lines.append("")

    for i in data:
        assigned = i["assignedTo"]["name"] if i.get("assignedTo") else "unassigned"
        lines.append(f'  {i["shortId"]:<24}  {i["priority"] or "?":>6}  {i["count"]:>6} events  {assigned}')
        lines.append(f'  {i["title"]}')
        lines.append(f'  first:{i["firstSeen"][:10]}  last:{i["lastSeen"][:10]}  {i["permalink"]}')
        lines.append("")

    return "\n".join(lines).rstrip()

def tool_get_issue_details(issue_id):
    _, _, _, base_url = _cfg()
    data, _ = get(f"{base_url}/issues/{issue_id}/")

    lines = [
        f'{data["shortId"]}  {data["title"]}',
        f'status:{data["status"]}  priority:{data.get("priority","?")}  events:{data["count"]}  users:{data["userCount"]}',
        f'first:{data["firstSeen"][:10]}  last:{data["lastSeen"][:10]}',
        f'culprit: {data.get("culprit","")}',
        f'url: {data["permalink"]}',
        "",
    ]

    # Latest event
    try:
        event, _ = get(f"{base_url}/issues/{issue_id}/events/latest/")
        env  = next((t["value"] for t in event.get("tags",[]) if t["key"]=="environment"), "?")
        rel  = (event.get("release") or {}).get("version", "?")
        lines += [
            f'LATEST EVENT  {event.get("dateCreated","")[:19]}',
            f'  env:{env}  release:{rel}',
        ]
        if event.get("user"):
            u = event["user"]
            lines.append(f'  user: {u.get("email") or u.get("username") or u.get("id","")}')

        # Exception
        exc_entry = next((e for e in event.get("entries",[]) if e["type"]=="exception"), None)
        if exc_entry:
            lines.append("")
            lines.append("EXCEPTION")
            for val in (exc_entry["data"].get("values") or []):
                lines.append(f'  {val.get("type","")}:{val.get("value","")}')
                for frame in reversed((val.get("stacktrace") or {}).get("frames") or [])[:5]:
                    lines.append(f'    {frame.get("filename","")}:{frame.get("lineNo","")}  {frame.get("function","")}')

        # Breadcrumbs
        bc_entry = next((e for e in event.get("entries",[]) if e["type"]=="breadcrumbs"), None)
        if bc_entry:
            crumbs = (bc_entry["data"].get("values") or [])[-8:]
            lines.append("")
            lines.append(f"BREADCRUMBS  (last {len(crumbs)})")
            for c in crumbs:
                msg = c.get("message") or json.dumps(c.get("data",{}))[:60]
                lines.append(f'  {c.get("timestamp","")[:19]}  {c.get("level","?"):>5}  {c.get("category","")}  {msg}')
    except Exception as e:
        lines.append(f"(could not fetch latest event: {e})")

    return "\n".join(lines)

def tool_resolve_issue(issue_id):
    _, _, _, base_url = _cfg()
    data = put(f"{base_url}/issues/{issue_id}/", {"status": "resolved"})
    return f'resolved  {data["id"]}  {data["status"]}'

def tool_ignore_issue(issue_id):
    _, _, _, base_url = _cfg()
    data = put(f"{base_url}/issues/{issue_id}/", {"status": "ignored"})
    return f'ignored  {data["id"]}  {data["status"]}'

# ── Dispatch ──────────────────────────────────────────────────────────────────

TOOLS = {
    "list_tools":         (tool_list_tools,         0, 0),
    "discover":           (tool_discover,            0, 0),
    "list_issues":        (tool_list_issues,         0, 2),
    "get_issue_details":  (tool_get_issue_details,   1, 1),
    "resolve_issue":      (tool_resolve_issue,       1, 1),
    "ignore_issue":       (tool_ignore_issue,        1, 1),
}

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    tool_name = args[0]
    if tool_name not in TOOLS:
        sys.exit(f"Unknown tool: {tool_name}\nRun: python sentry_api.py list_tools")

    fn, min_args, max_args = TOOLS[tool_name]
    call_args = args[1:]

    if len(call_args) < min_args or len(call_args) > max_args:
        sys.exit(f"Usage error: {tool_name} expects {min_args}–{max_args} args, got {len(call_args)}")

    try:
        print(fn(*call_args))
    except Exception as e:
        sys.exit(f"Error: {e}")