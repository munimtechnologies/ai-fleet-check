#!/usr/bin/env python3
"""ai-fleet-check: run the Dify and Open WebUI hardening checks over every
client's deployment files at once, for IT providers (MSPs) who run self-hosted
AI apps for several small businesses.

It writes one fleet summary (which clients need attention first, which problems
repeat across clients, what changed since last time) and one plain-language
report per client. Read-only, standard library only, works offline, and it never
prints secret values: it only reads files you already have, it never contacts a
client's server. Made with AI agents for MV2 of Munim, Inc. Apache-2.0.

    python3 fleet_check.py fleet.json --out reports/
    python3 fleet_check.py fleet.json --out reports/2026-12 --previous reports/2026-11/fleet.json

fleet.json lists one entry per deployment (paths are relative to fleet.json):

    {"provider": "Example IT",
     "deployments": [
       {"client": "Acme Dental", "app": "dify",      "path": "acme/dify/docker"},
       {"client": "Acme Dental", "app": "openwebui", "path": "acme/open-webui"},
       {"client": "Baker Law",   "app": "openwebui", "files": ["baker/compose.yml", "baker/.env"]}
     ]}
"""

import argparse
import importlib.util
import json
import os
import re
import sys
import textwrap

__version__ = "0.1.0"
REPO = "https://github.com/munimtechnologies/ai-fleet-check"
SEVERITIES = ["critical", "high", "medium", "low", "info"]
RANK = {s: i for i, s in enumerate(SEVERITIES)}

# app name -> (module file, module name, upstream repo)
CHECKERS = {
    "dify": ("dify_hardening_check.py", "dify_hardening_check",
             "https://github.com/munimtechnologies/dify-hardening-check"),
    "openwebui": ("owui_hardening_check.py", "owui_hardening_check",
                  "https://github.com/munimtechnologies/openwebui-hardening-check"),
}
APP_NAMES = {"dify": "Dify", "openwebui": "Open WebUI"}
ALIASES = {"open-webui": "openwebui", "open_webui": "openwebui", "owui": "openwebui"}

# Files Docker Compose reads by itself in an Open WebUI folder, plus a pip
# install's key file (only its date is used by the checker).
OWUI_NAMES = [".env", "docker-compose.yml", "docker-compose.yaml", "docker-compose.override.yml",
              "docker-compose.override.yaml", "compose.yml", "compose.yaml", ".webui_secret_key"]


class FleetError(Exception):
    pass


# ---------------------------------------------------------------- loading

def load_checker(app, checkers_dir):
    filename, modname, _ = CHECKERS[app]
    path = os.path.join(checkers_dir, filename)
    if not os.path.isfile(path):
        raise FleetError("%s not found in %s (download it from %s)" % (filename, checkers_dir, CHECKERS[app][2]))
    spec = importlib.util.spec_from_file_location(modname, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    spec.loader.exec_module(module)
    return module


def normalise_app(app):
    app = str(app or "").strip().lower()
    app = ALIASES.get(app, app)
    if app not in CHECKERS:
        raise FleetError("unknown app %r (use one of: %s)" % (app, ", ".join(sorted(CHECKERS))))
    return app


def load_fleet(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except ValueError as e:
        raise FleetError("%s is not valid JSON: %s" % (path, e))
    if isinstance(data, list):
        data = {"deployments": data}
    entries = data.get("deployments") or data.get("clients")
    if not isinstance(entries, list) or not entries:
        raise FleetError("%s has no \"deployments\" list" % path)
    base = os.path.dirname(os.path.abspath(path))
    out = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or not e.get("client"):
            raise FleetError("entry %d needs a \"client\" name" % (i + 1))
        app = normalise_app(e.get("app"))
        rel = list(e["files"]) if e.get("files") else ([e["path"]] if e.get("path") else [])
        if not rel:
            raise FleetError("entry %d (%s) needs a \"path\" or \"files\"" % (i + 1, e["client"]))
        out.append({"client": str(e["client"]), "app": app, "label": e.get("label") or "",
                    "paths": rel, "abs": [os.path.join(base, p) for p in rel]})
    return {"provider": data.get("provider") or "", "deployments": out}


def owui_files(paths):
    """A folder stands for the files Docker Compose reads there; files are used as given."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            found = [os.path.join(p, n) for n in OWUI_NAMES if os.path.isfile(os.path.join(p, n))]
            if not found:
                raise FleetError("no .env, compose file or .webui_secret_key in %s" % p)
            out += found
        else:
            out.append(p)
    return out


# ---------------------------------------------------------------- checking

def check_deployment(d, checkers):
    """Runs the app's checker on local files only (never --url)."""
    result = {"client": d["client"], "app": d["app"], "label": d["label"], "paths": d["paths"],
              "version": None, "checked": [], "findings": [], "error": None}
    try:
        missing = [p for p, a in zip(d["paths"], d["abs"]) if not os.path.exists(a)]
        if missing:
            raise FleetError("not found: %s" % ", ".join(missing))
        module = checkers[d["app"]]
        files = d["abs"] if d["app"] == "dify" else owui_files(d["abs"])
        findings, sources, label = module.run(files)
        result.update(version=label, checked=list(sources), findings=sorted(findings, key=lambda f: RANK[f["severity"]]))
    except (FleetError, OSError, ValueError) as e:
        result["error"] = str(e)
    result["counts"] = counts(result["findings"])
    result["worst"] = worst(result)
    return result


def counts(findings):
    c = {s: 0 for s in SEVERITIES}
    for f in findings:
        c[f["severity"]] += 1
    return c


def worst(result):
    if result["error"]:
        return "error"
    for s in SEVERITIES:
        if result["counts"][s]:
            return s
    return "none"


def priority(result):
    """Sort key: deployments that could not be checked first, then by their most severe findings."""
    c = result["counts"]
    return (0 if result["error"] else 1, -c["critical"], -c["high"], -c["medium"], -c["low"],
            result["client"].lower(), result["app"])


def issue_key(f):
    """The same problem on two deployments has the same key: the setting it is about, else the title
    with numbers removed (titles may carry version numbers or counts). Port findings share the setting
    "ports", so they are told apart by their title (which names the service)."""
    if f.get("setting") and f["setting"] != "ports":
        return f["setting"]
    return re.sub(r"\d+(\.\d+)*", "#", f["title"])


def deployment_id(r):
    return "%s / %s%s" % (r["client"], APP_NAMES[r["app"]], (" (%s)" % r["label"]) if r["label"] else "")


def common_issues(results):
    """Problems found on more than one deployment, most widespread and most severe first."""
    groups = {}
    for r in results:
        for f in r["findings"]:
            if f["severity"] == "info":
                continue
            k = (r["app"], issue_key(f))
            g = groups.setdefault(k, {"app": r["app"], "key": k[1], "title": f["title"], "severity": f["severity"],
                                      "fix": f["fix"], "deployments": []})
            if RANK[f["severity"]] < RANK[g["severity"]]:
                g.update(severity=f["severity"], title=f["title"], fix=f["fix"])
            if deployment_id(r) not in g["deployments"]:
                g["deployments"].append(deployment_id(r))
    out = [g for g in groups.values() if len(g["deployments"]) > 1]
    return sorted(out, key=lambda g: (-len(g["deployments"]), RANK[g["severity"]], g["title"]))


def changes(results, previous):
    """New and fixed findings against an earlier fleet.json (same client, app and label)."""
    if not previous:
        return None
    before = {}
    for r in previous.get("results", []):
        if r.get("error"):
            continue
        before[(r["client"], r["app"], r.get("label", ""))] = {issue_key(f): f for f in r.get("findings", [])
                                                               if f["severity"] != "info"}
    new, fixed = [], []
    for r in results:
        if r["error"]:
            continue
        key = (r["client"], r["app"], r["label"])
        now = {issue_key(f): f for f in r["findings"] if f["severity"] != "info"}
        if key not in before:
            continue
        for k, f in now.items():
            if k not in before[key]:
                new.append({"deployment": deployment_id(r), "severity": f["severity"], "title": f["title"]})
        for k, f in before[key].items():
            if k not in now:
                fixed.append({"deployment": deployment_id(r), "severity": f["severity"], "title": f["title"]})
    order = lambda x: (RANK[x["severity"]], x["deployment"], x["title"])
    return {"new": sorted(new, key=order), "fixed": sorted(fixed, key=order)}


def run_fleet(fleet, checkers_dir, previous=None):
    apps = sorted({d["app"] for d in fleet["deployments"]})
    checkers, versions = {}, {}
    for app in apps:
        checkers[app] = load_checker(app, checkers_dir)
        versions[app] = {"version": getattr(checkers[app], "__version__", "?"),
                         "data_date": getattr(checkers[app], "DATA_DATE", "?")}
    results = sorted((check_deployment(d, checkers) for d in fleet["deployments"]), key=priority)
    total = counts([f for r in results for f in r["findings"]])
    return {"tool": "ai-fleet-check", "version": __version__, "provider": fleet["provider"],
            "checkers": versions, "deployments": len(results),
            "errors": sum(1 for r in results if r["error"]), "counts": total,
            "results": results, "common": common_issues(results), "changes": changes(results, previous)}


# ---------------------------------------------------------------- reports

FOOTER = ("General technical information, not a security certification. Checks only the files listed; "
          "no server was contacted. Made with AI agents for MV2 of Munim, Inc.: %s" % REPO)


def _count_text(c):
    return ", ".join("%d %s" % (c[s], s) for s in SEVERITIES[:4] if c[s]) or "no problems found"


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_fleet_markdown(report):
    title = "AI fleet check" + (" for %s" % report["provider"] if report["provider"] else "")
    lines = ["# " + title, "",
             "%d deployments checked with %s. Totals: %s." % (
                 report["deployments"],
                 " and ".join("%s hardening check %s (data %s)" % (APP_NAMES[a], v["version"], v["data_date"])
                              for a, v in sorted(report["checkers"].items())),
                 _count_text(report["counts"])), ""]
    if report["errors"]:
        lines += ["**%d deployment(s) could not be checked** (see the table)." % report["errors"], ""]
    lines += ["## Which deployments need attention first", "",
              "| Client | App | Version | Critical | High | Medium | Low | Most urgent |",
              "|---|---|---|---|---|---|---|---|"]
    for r in report["results"]:
        c = r["counts"]
        top = ("could not check: " + r["error"]) if r["error"] else (r["findings"][0]["title"] if r["findings"] and
                                                                      r["findings"][0]["severity"] != "info" else "-")
        lines.append("| %s | %s | %s | %d | %d | %d | %d | %s |" % (
            _cell(r["client"]), _cell(APP_NAMES[r["app"]] + (" (%s)" % r["label"] if r["label"] else "")),
            _cell((r["version"] or "unknown").split(" ")[0]), c["critical"], c["high"], c["medium"], c["low"],
            _cell(top)))
    lines.append("")
    if report["common"]:
        lines += ["## Problems on more than one deployment", "",
                  "Fixing these once in your standard build fixes them everywhere.", ""]
        for g in report["common"]:
            lines.append("- **%s** (%s, %s, %d deployments: %s). *Fix:* %s" % (
                g["title"], g["severity"], APP_NAMES[g["app"]], len(g["deployments"]),
                "; ".join(g["deployments"]), g["fix"].replace("\n", " ")))
        lines.append("")
    ch = report["changes"]
    if ch is not None:
        lines += ["## Since the previous check", "",
                  "%d fixed, %d new." % (len(ch["fixed"]), len(ch["new"])), ""]
        for label, items in (("Fixed", ch["fixed"]), ("New", ch["new"])):
            for x in items:
                lines.append("- %s: %s: %s (%s)" % (label, x["deployment"], x["title"], x["severity"]))
        lines.append("")
    lines += ["_%s_" % FOOTER]
    return "\n".join(lines)


def render_client_markdown(client, results, provider=""):
    """A report an IT provider can send to a client: what was checked, what to fix, in order."""
    lines = ["# Security check of your self-hosted AI apps: %s" % client, ""]
    intro = ("%s checked the settings files of the AI apps it runs for you" % provider) if provider else \
        "This report checks the settings files of your self-hosted AI apps"
    lines += [intro + " against each project's published hardening guidance and known security advisories. "
              "Passwords and keys are never shown in this report; only which settings need a change.", ""]
    for r in results:
        name = APP_NAMES[r["app"]] + (" (%s)" % r["label"] if r["label"] else "")
        lines += ["## " + name, ""]
        if r["error"]:
            lines += ["Could not be checked: %s" % r["error"], ""]
            continue
        lines += ["Version: %s. Result: %s." % ((r["version"] or "unknown").split(" ")[0], _count_text(r["counts"])), ""]
        actionable = [f for f in r["findings"] if f["severity"] != "info"]
        if not actionable:
            lines += ["Nothing to fix in the files checked.", ""]
        for n, f in enumerate(actionable, 1):
            lines.append("%d. **%s** (%s)" % (n, f["title"], f["severity"]))
            if f.get("detail"):
                lines.append("   " + f["detail"].replace("\n", " "))
            lines.append("   *What to do:* %s ([source](%s))" % (f["fix"].replace("\n", " "), f["source"]))
            lines.append("")
        notes = [f for f in r["findings"] if f["severity"] == "info"]
        if notes:
            lines += ["Notes:"] + ["- %s" % f["title"] for f in notes] + [""]
    lines += ["_%s_" % FOOTER]
    return "\n".join(lines)


def render_text(report):
    lines = ["AI fleet check %s: %d deployments, %s" % (__version__, report["deployments"],
                                                         _count_text(report["counts"]))]
    for r in report["results"]:
        state = ("ERROR " + r["error"]) if r["error"] else _count_text(r["counts"])
        lines.append("  %-40s %s" % (deployment_id(r)[:40], state))
    if report["common"]:
        lines.append("On more than one deployment:")
        for g in report["common"][:10]:
            lines += textwrap.wrap("%s (%s, %d deployments)" % (g["title"], g["severity"], len(g["deployments"])),
                                   100, initial_indent="  ", subsequent_indent="    ")
    if report["changes"] is not None:
        lines.append("Since the previous check: %d fixed, %d new" % (len(report["changes"]["fixed"]),
                                                                      len(report["changes"]["new"])))
    return "\n".join(lines)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "client"


def write_reports(report, out_dir):
    os.makedirs(os.path.join(out_dir, "clients"), exist_ok=True)
    written = []
    path = os.path.join(out_dir, "fleet.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    written.append(path)
    path = os.path.join(out_dir, "fleet.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_fleet_markdown(report) + "\n")
    written.append(path)
    by_client, used = {}, {}
    for r in report["results"]:
        by_client.setdefault(r["client"], []).append(r)
    for client in sorted(by_client):
        s = slug(client)
        used[s] = used.get(s, 0) + 1
        name = s if used[s] == 1 else "%s-%d" % (s, used[s])
        path = os.path.join(out_dir, "clients", name + ".md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(render_client_markdown(client, by_client[client], report["provider"]) + "\n")
        written.append(path)
    return written


# ---------------------------------------------------------------- command line

def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    p = argparse.ArgumentParser(
        prog="fleet_check.py",
        description="Check every client's self-hosted Dify and Open WebUI deployment files at once and write a "
                    "fleet summary plus one report per client. Read-only; offline; secret values are never printed.")
    p.add_argument("fleet", help="fleet.json listing client, app (dify or openwebui) and path or files")
    p.add_argument("--out", help="folder for fleet.json, fleet.md and clients/*.md")
    p.add_argument("--previous", help="an earlier fleet.json, to list what was fixed and what is new")
    p.add_argument("--checkers", default=here,
                   help="folder holding dify_hardening_check.py and owui_hardening_check.py (default: next to this file)")
    p.add_argument("--json", action="store_true", help="print the fleet JSON instead of the text summary")
    p.add_argument("--fail-on", choices=SEVERITIES[:4] + ["never"], default="never",
                   help="exit with 1 when any deployment has a finding this severe or worse, or could not be checked")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)
    try:
        fleet = load_fleet(args.fleet)
        previous = None
        if args.previous:
            with open(args.previous, encoding="utf-8") as f:
                previous = json.load(f)
        report = run_fleet(fleet, args.checkers, previous)
    except (FleetError, OSError, ValueError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    if args.out:
        write_reports(report, args.out)
    print(json.dumps(report, indent=2) if args.json else render_text(report))
    if args.fail_on != "never":
        if report["errors"] or any(RANK[f["severity"]] <= RANK[args.fail_on]
                                   for r in report["results"] for f in r["findings"]):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
