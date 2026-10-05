#!/usr/bin/env python3
"""Google Tag Manager API CLI: inspect a workspace and audit it.

Read commands run with a read-only scope. Write commands (pause, unpause,
delete, create-version, publish) default to a DRY RUN that prints what would
change; nothing is sent until you add --apply, and only then are edit/publish
scopes requested.

Setup: see README. The service account needs access to the GTM container
(Admin > User management), and the Tag Manager API must be enabled.

Identify the container with flags or environment variables:
  --account-id   / GTM_ACCOUNT_ID    numeric account ID
  --container-id / GTM_CONTAINER_ID  numeric container ID (not GTM-XXXXXXX)
  --workspace-id / GTM_WORKSPACE_ID  numeric workspace ID

Usage:
  python3 gtm.py workspaces list
  python3 gtm.py tags list
  python3 gtm.py tags get 12
  python3 gtm.py triggers list
  python3 gtm.py variables list
  python3 gtm.py audit
  python3 gtm.py workspace status
  python3 gtm.py versions list
  python3 gtm.py tags pause 12              # dry run
  python3 gtm.py tags pause 12 --apply      # actually pause
  python3 gtm.py create-version --name "Cleanup" --apply
  python3 gtm.py publish 34 --apply
"""

import argparse
import json
import os
import re
import sys

SCOPE_READ = ["https://www.googleapis.com/auth/tagmanager.readonly"]
SCOPE_WRITE = [
    "https://www.googleapis.com/auth/tagmanager.edit.containers",
    "https://www.googleapis.com/auth/tagmanager.publish",
    "https://www.googleapis.com/auth/tagmanager.readonly",
]

MEASUREMENT_ID_RE = re.compile(r"\bG-[A-Z0-9]{6,}\b")
VARIABLE_REF_RE = re.compile(r"\{\{([^{}]+)\}\}")


# ---------------------------------------------------------------------------
# Audit logic (pure: takes API dicts, returns findings)
# ---------------------------------------------------------------------------

def referenced_variable_names(*entity_lists):
    """Names used as {{Name}} anywhere inside the given tags/triggers/variables."""
    names = set()
    for entities in entity_lists:
        for e in entities:
            names.update(VARIABLE_REF_RE.findall(json.dumps(e)))
    return names


def audit_container(tags, triggers, variables):
    """Return a list of findings: dicts with severity, check, item, message.

    Checks are heuristics. Each message says what to verify before acting.
    """
    findings = []

    def add(sev, check, item, msg):
        findings.append({"severity": sev, "check": check, "item": item, "message": msg})

    used_triggers = set()
    for t in tags:
        used_triggers.update(t.get("firingTriggerId", []))
        used_triggers.update(t.get("blockingTriggerId", []))

    name_counts = {}
    for t in tags:
        name_counts[t["name"]] = name_counts.get(t["name"], 0) + 1

    for t in tags:
        label = f"tag {t.get('tagId', '?')} '{t['name']}'"
        if t.get("paused"):
            add("info", "paused_tag", label, "Paused. Remove it if it is no longer needed.")
        elif not t.get("firingTriggerId"):
            add("warn", "tag_without_trigger", label,
                "No firing trigger. It only runs if another tag fires it via tag sequencing.")
        if name_counts[t["name"]] > 1:
            add("warn", "duplicate_tag_name", label, "Another tag has the same name.")
        if t.get("type") == "html":
            add("info", "custom_html", label, "Custom HTML tag. Review the code and who owns it.")
        if t.get("type") == "ua":
            add("warn", "legacy_universal_analytics", label,
                "Universal Analytics tag type. UA no longer processes data.")
        blob = json.dumps(t.get("parameter", []))
        if MEASUREMENT_ID_RE.search(blob):
            add("info", "hardcoded_measurement_id", label,
                "GA4 measurement ID typed into the tag. A constant variable keeps it in one place.")

    for tr in triggers:
        if tr.get("triggerId") not in used_triggers:
            add("info", "unused_trigger", f"trigger {tr.get('triggerId', '?')} '{tr['name']}'",
                "Not used by any tag as a firing or blocking trigger.")

    for v in variables:
        # Exclude the variable's own definition so a self-reference does not
        # hide an otherwise unused variable.
        others = [x for x in variables if x is not v]
        if v["name"] not in referenced_variable_names(tags, triggers, others):
            add("info", "unused_variable", f"variable {v.get('variableId', '?')} '{v['name']}'",
                "No {{name}} reference found in tags, triggers or other variables. "
                "It may still be used by a built-in feature; check before deleting.")
    return findings


def format_findings(findings):
    if not findings:
        return "No findings."
    order = {"warn": 0, "info": 1}
    lines = []
    for f in sorted(findings, key=lambda x: (order.get(x["severity"], 9), x["check"])):
        lines.append(f"[{f['severity'].upper():<4}] {f['check']}: {f['item']}\n         {f['message']}")
    warns = sum(1 for f in findings if f["severity"] == "warn")
    lines.append(f"\n{len(findings)} findings ({warns} warn, {len(findings) - warns} info)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# API access
# ---------------------------------------------------------------------------

class Ctx:
    """Holds IDs and builds the service lazily with the right scopes."""

    def __init__(self, args):
        self.account = args.account_id
        self.container = args.container_id
        self.workspace = args.workspace_id
        self._service = {}

    def require(self, *names):
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            sys.exit("Missing: " + ", ".join(f"--{m}-id / GTM_{m.upper()}_ID" for m in missing))

    @property
    def container_path(self):
        self.require("account", "container")
        return f"accounts/{self.account}/containers/{self.container}"

    @property
    def workspace_path(self):
        self.require("account", "container", "workspace")
        return f"{self.container_path}/workspaces/{self.workspace}"

    def service(self, write=False):
        if write not in self._service:
            key = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            if not key:
                sys.exit("Set GOOGLE_APPLICATION_CREDENTIALS to your service account JSON path.")
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            creds = service_account.Credentials.from_service_account_file(
                key, scopes=SCOPE_WRITE if write else SCOPE_READ)
            self._service[write] = build("tagmanager", "v2", credentials=creds,
                                         cache_discovery=False)
        return self._service[write]

    def ws(self, write=False):
        return self.service(write).accounts().containers().workspaces()


def pp(obj):
    print(json.dumps(obj, indent=2, default=str))


def list_entities(ctx, kind):
    """kind: tags, triggers or variables. Follows pagination."""
    resource = getattr(ctx.ws(), kind)()
    key = kind[:-1]
    items, token = [], None
    while True:
        res = resource.list(parent=ctx.workspace_path, **({"pageToken": token} if token else {})).execute()
        items.extend(res.get(key, []))
        token = res.get("nextPageToken")
        if not token:
            return items


# ---------------------------------------------------------------------------
# Read commands
# ---------------------------------------------------------------------------

def cmd_workspaces_list(ctx, args):
    res = ctx.service().accounts().containers().workspaces().list(parent=ctx.container_path).execute()
    for w in res.get("workspace", []):
        print(f"{w['workspaceId']:<8} {w['name']}")


def cmd_list(ctx, args, kind):
    items = list_entities(ctx, kind)
    if args.json:
        return pp(items)
    id_key = {"tags": "tagId", "triggers": "triggerId", "variables": "variableId"}[kind]
    print(f"{'ID':<8} {'Type':<22} {'Notes':<14} Name")
    print("-" * 70)
    for e in sorted(items, key=lambda x: x["name"].lower()):
        note = "paused" if e.get("paused") else ""
        if kind == "tags" and not e.get("firingTriggerId") and not e.get("paused"):
            note = "no trigger"
        print(f"{e[id_key]:<8} {e.get('type', '?'):<22} {note:<14} {e['name']}")
    print(f"\nTotal: {len(items)} {kind}")


def cmd_get(ctx, args, kind):
    pp(getattr(ctx.ws(), kind)().get(path=f"{ctx.workspace_path}/{kind}/{args.id}").execute())


def cmd_audit(ctx, args):
    tags, triggers, variables = (list_entities(ctx, k) for k in ("tags", "triggers", "variables"))
    findings = audit_container(tags, triggers, variables)
    if args.json:
        return pp(findings)
    print(f"Audited {len(tags)} tags, {len(triggers)} triggers, {len(variables)} variables\n")
    print(format_findings(findings))


def cmd_workspace_status(ctx, args):
    st = ctx.ws().getStatus(path=ctx.workspace_path).execute()
    changes = st.get("workspaceChange", [])
    if not changes:
        return print("No pending changes.")
    print(f"Pending changes ({len(changes)}):")
    for ch in changes:
        entity = ch.get("tag") or ch.get("trigger") or ch.get("variable") or {}
        print(f"  [{ch.get('changeStatus', '?')}] {entity.get('name', '?')}")


def cmd_versions_list(ctx, args):
    svc = ctx.service()
    headers = svc.accounts().containers().version_headers().list(parent=ctx.container_path).execute()
    live_id = None
    try:
        live_id = svc.accounts().containers().versions().live(parent=ctx.container_path).execute().get("containerVersionId")
    except Exception:
        pass
    versions = sorted(headers.get("containerVersionHeader", []),
                      key=lambda v: int(v.get("containerVersionId", 0)), reverse=True)
    print(f"{'ID':<8} {'Live':<5} Name")
    for v in versions[:20]:
        print(f"{v['containerVersionId']:<8} {'*' if v['containerVersionId'] == live_id else '':<5} "
              f"{v.get('name', '(unnamed)')}")
    print(f"\nShowing {min(20, len(versions))} of {len(versions)} versions")


# ---------------------------------------------------------------------------
# Write commands (dry run unless --apply)
# ---------------------------------------------------------------------------

def dry_run_or(args, description, action):
    """Print the planned change. Run `action` only when --apply is set."""
    if not args.apply:
        print(f"[dry run] would {description}")
        print("Re-run with --apply to make this change.")
        return None
    print(f"Applying: {description}")
    return action()


def cmd_tag_set_paused(ctx, args, paused):
    path = f"{ctx.workspace_path}/tags/{args.id}"
    tag = ctx.ws().tags().get(path=path).execute()
    verb = "pause" if paused else "unpause"
    if bool(tag.get("paused")) == paused:
        return print(f"Tag '{tag['name']}' is already {'paused' if paused else 'active'}. Nothing to do.")

    def do():
        write_tag = ctx.ws(write=True).tags().get(path=path).execute()
        write_tag["paused"] = paused
        ctx.ws(write=True).tags().update(path=path, body=write_tag,
                                         fingerprint=write_tag["fingerprint"]).execute()
        print("Done. The change is in the workspace; it is not live until you create and publish a version.")
    dry_run_or(args, f"{verb} tag {args.id} '{tag['name']}' (type {tag.get('type')})", do)


def cmd_tag_delete(ctx, args):
    path = f"{ctx.workspace_path}/tags/{args.id}"
    tag = ctx.ws().tags().get(path=path).execute()

    def do():
        ctx.ws(write=True).tags().delete(path=path).execute()
        print("Deleted from the workspace. Not live until a version is published.")
    dry_run_or(args, f"DELETE tag {args.id} '{tag['name']}' (type {tag.get('type')})", do)


def cmd_create_version(ctx, args):
    def do():
        res = ctx.ws(write=True).create_version(
            path=ctx.workspace_path, body={"name": args.name, "notes": args.notes or ""}).execute()
        if res.get("compilerError"):
            print("Compiler errors found; version not usable:")
            pp(res["compilerError"])
        else:
            vid = res.get("containerVersion", {}).get("containerVersionId", "?")
            print(f"Created version {vid}. Publish it with: gtm.py publish {vid} --apply")
    dry_run_or(args, f"create a container version named '{args.name}' from workspace {ctx.workspace}", do)


def cmd_publish(ctx, args):
    path = f"{ctx.container_path}/versions/{args.version_id}"

    def do():
        res = ctx.service(write=True).accounts().containers().versions().publish(path=path).execute()
        v = res.get("containerVersion", {})
        print(f"Published version {v.get('containerVersionId')}: {v.get('name', '(unnamed)')}")
    dry_run_or(args, f"PUBLISH version {args.version_id} to the live container", do)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(description="Google Tag Manager API CLI")
    ap.add_argument("--account-id", default=os.environ.get("GTM_ACCOUNT_ID"))
    ap.add_argument("--container-id", default=os.environ.get("GTM_CONTAINER_ID"))
    ap.add_argument("--workspace-id", default=os.environ.get("GTM_WORKSPACE_ID"))
    ap.add_argument("--json", action="store_true", help="Raw JSON output for list/audit")
    sub = ap.add_subparsers(dest="resource", required=True)

    def apply_flag(p):
        p.add_argument("--apply", action="store_true",
                       help="Make the change. Without it the command only prints the plan.")

    sub.add_parser("audit", help="Heuristic checks for common container issues")
    sub.add_parser("workspaces").add_subparsers(dest="action", required=True).add_parser("list")
    sub.add_parser("workspace").add_subparsers(dest="action", required=True).add_parser("status")
    sub.add_parser("versions").add_subparsers(dest="action", required=True).add_parser("list")

    for kind in ("tags", "triggers", "variables"):
        p = sub.add_parser(kind)
        s = p.add_subparsers(dest="action", required=True)
        s.add_parser("list")
        s.add_parser("get").add_argument("id")
        if kind == "tags":
            for name in ("pause", "unpause", "delete"):
                sp = s.add_parser(name)
                sp.add_argument("id")
                apply_flag(sp)

    p = sub.add_parser("create-version")
    p.add_argument("--name", required=True)
    p.add_argument("--notes")
    apply_flag(p)
    p = sub.add_parser("publish")
    p.add_argument("version_id")
    apply_flag(p)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    ctx = Ctx(args)
    r, a = args.resource, getattr(args, "action", None)

    if r in ("tags", "triggers", "variables"):
        if a == "list":
            return cmd_list(ctx, args, r)
        if a == "get":
            return cmd_get(ctx, args, r)
        if a in ("pause", "unpause"):
            return cmd_tag_set_paused(ctx, args, a == "pause")
        if a == "delete":
            return cmd_tag_delete(ctx, args)
    handlers = {
        ("audit", None): cmd_audit,
        ("create-version", None): cmd_create_version,
        ("publish", None): cmd_publish,
        ("workspaces", "list"): cmd_workspaces_list,
        ("workspace", "status"): cmd_workspace_status,
        ("versions", "list"): cmd_versions_list,
    }
    handlers[(r, a)](ctx, args)


if __name__ == "__main__":
    main()
