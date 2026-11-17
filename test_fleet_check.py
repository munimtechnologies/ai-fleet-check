import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fleet_check as fc  # noqa: E402
import dify_hardening_check as dhc  # noqa: E402

# A Dify 1.19 docker/ folder: the published defaults live in envs/**/*.defaults.
DIFY_119 = {
    ".env": "COMPOSE_PROFILES=weaviate,postgresql\nDIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN=\n",
    "docker-compose.yaml": "services:\n  api:\n    image: langgenius/dify-api:1.19.0\n",
    os.path.join("envs", "databases", "db-postgres.defaults"):
        "DB_USERNAME=${DB_USERNAME:-postgres}\n"
        "DB_PASSWORD=${DB_PASSWORD:-difyai123456}\nPOSTGRES_PASSWORD=${DB_PASSWORD:-difyai123456}\n",
    os.path.join("envs", "core-services", "plugin-daemon.defaults"):
        "SERVER_KEY=${PLUGIN_DAEMON_KEY:-%s}\n" % dhc.PUBLISHED_KEYS["PLUGIN_DAEMON_KEY"],
    os.path.join("envs", "core-services", "sandbox.defaults"):
        "SANDBOX_API_KEY=${SANDBOX_API_KEY:-dify-sandbox}\nAPI_KEY=${SANDBOX_API_KEY:-dify-sandbox}\n",
}
STRONG_ENV = ("DB_PASSWORD=q8Vh2mZ0rT4w\nPLUGIN_DAEMON_KEY=Zx81kQ0pLm\nSANDBOX_API_KEY=Pq7rS2tUv\n"
              "DIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN=f0e1d2c3b4a5\n")
STRONG_VALUES = ["q8Vh2mZ0rT4w", "Zx81kQ0pLm", "Pq7rS2tUv", "f0e1d2c3b4a5"]

OWUI_COMPOSE = """services:
  open-webui:
    image: ghcr.io/open-webui/open-webui:v0.11.2
    ports:
      - 3000:8080
    environment:
      - 'WEBUI_SECRET_KEY='
      - 'ENABLE_SIGNUP=true'
"""

FLEET = {
    "provider": "Example IT",
    "deployments": [
        {"client": "Acme Dental", "app": "dify", "path": "acme/dify/docker"},
        {"client": "Acme Dental", "app": "open-webui", "path": "acme/owui"},
        {"client": "Baker Law", "app": "dify", "path": "baker/docker"},
        {"client": "Dana & Co", "app": "dify", "path": "dana/docker"},
        {"client": "Eve Studio", "app": "openwebui", "path": "eve/missing"},
    ],
}


def write(base, rel, text):
    path = os.path.join(base, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def all_text(folder):
    out = []
    for root, _, names in os.walk(folder):
        for n in names:
            with open(os.path.join(root, n), encoding="utf-8") as f:
                out.append(f.read())
    return "\n".join(out)


class FleetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        for folder in ("acme/dify/docker", "baker/docker", "dana/docker"):
            for rel, text in DIFY_119.items():
                write(self.d, os.path.join(folder, rel), text)
        write(self.d, "dana/docker/.env", STRONG_ENV)
        write(self.d, "acme/owui/docker-compose.yml", OWUI_COMPOSE)
        write(self.d, "acme/owui/notes.txt", "WEBUI_AUTH=False\n")   # not a file Compose reads
        self.fleet_path = os.path.join(self.d, "fleet.json")
        write(self.d, "fleet.json", json.dumps(FLEET))

    def tearDown(self):
        self.tmp.cleanup()

    def report(self, previous=None):
        return fc.run_fleet(fc.load_fleet(self.fleet_path), HERE, previous)

    def test_load_fleet_resolves_paths_and_aliases(self):
        fleet = fc.load_fleet(self.fleet_path)
        self.assertEqual(fleet["provider"], "Example IT")
        self.assertEqual([d["app"] for d in fleet["deployments"]], ["dify", "openwebui", "dify", "dify", "openwebui"])
        self.assertTrue(fleet["deployments"][0]["abs"][0].startswith(self.d))

    def test_bad_fleet_files(self):
        write(self.d, "bad.json", json.dumps({"deployments": [{"client": "X", "app": "n8n", "path": "x"}]}))
        with self.assertRaises(fc.FleetError):
            fc.load_fleet(os.path.join(self.d, "bad.json"))
        write(self.d, "bad2.json", json.dumps({"deployments": [{"app": "dify", "path": "x"}]}))
        with self.assertRaises(fc.FleetError):
            fc.load_fleet(os.path.join(self.d, "bad2.json"))
        write(self.d, "bad3.json", "{not json")
        with self.assertRaises(fc.FleetError):
            fc.load_fleet(os.path.join(self.d, "bad3.json"))

    def test_owui_folder_reads_only_compose_files(self):
        files = fc.owui_files([os.path.join(self.d, "acme/owui")])
        self.assertEqual([os.path.basename(f) for f in files], ["docker-compose.yml"])
        with self.assertRaises(fc.FleetError):
            fc.owui_files([os.path.join(self.d, "baker")])

    def test_priorities_and_counts(self):
        r = self.report()
        self.assertEqual(r["deployments"], 5)
        self.assertEqual(r["errors"], 1)
        first = r["results"][0]
        self.assertEqual(first["client"], "Eve Studio")
        self.assertIn("not found", first["error"])
        self.assertEqual(first["worst"], "error")
        last = r["results"][-1]
        self.assertEqual(last["client"], "Dana & Co")
        self.assertFalse([f for f in last["findings"] if f["setting"] == "credentials"])
        acme = [x for x in r["results"] if x["client"] == "Acme Dental" and x["app"] == "dify"][0]
        self.assertTrue(acme["version"].startswith("1.19.0"))
        self.assertTrue([f for f in acme["findings"] if f["setting"] == "credentials"])
        owui = [x for x in r["results"] if x["app"] == "openwebui" and not x["error"]][0]
        self.assertTrue(owui["findings"])
        self.assertFalse(any(f.get("setting") == "WEBUI_AUTH" for f in owui["findings"]))
        self.assertEqual(sum(r["counts"].values()), sum(len(x["findings"]) for x in r["results"]))

    def test_common_issues_span_clients(self):
        common = self.report()["common"]
        by_key = {(g["app"], g["key"]): g for g in common}
        self.assertEqual(by_key[("dify", "credentials")]["deployments"], ["Acme Dental / Dify", "Baker Law / Dify"])
        self.assertEqual(len(by_key[("dify", "CONSOLE_CORS_ALLOW_ORIGINS")]["deployments"]), 3)
        self.assertEqual(common[0]["key"], "CONSOLE_CORS_ALLOW_ORIGINS")   # the most widespread comes first
        for g in common:
            self.assertGreater(len(g["deployments"]), 1)

    def test_reports_never_contain_secret_values(self):
        out = os.path.join(self.d, "out")
        written = fc.write_reports(self.report(), out)
        names = sorted(os.path.relpath(p, out).replace(os.sep, "/") for p in written)
        self.assertEqual(names, ["clients/acme-dental.md", "clients/baker-law.md", "clients/dana-co.md",
                                 "clients/eve-studio.md", "fleet.json", "fleet.md"])
        text = all_text(out)
        for value in ["difyai123456", "dify-sandbox"] + list(dhc.PUBLISHED_VALUES) + STRONG_VALUES:
            self.assertNotIn(value, text)
        self.assertNotIn(self.d, open(os.path.join(out, "fleet.md"), encoding="utf-8").read())
        fleet_md = open(os.path.join(out, "fleet.md"), encoding="utf-8").read()
        self.assertIn("# AI fleet check for Example IT", fleet_md)
        self.assertIn("Problems on more than one deployment", fleet_md)
        self.assertIn("Made with AI agents for MV2 of Munim, Inc.", fleet_md)
        acme_md = open(os.path.join(out, "clients", "acme-dental.md"), encoding="utf-8").read()
        self.assertIn("## Dify", acme_md)
        self.assertIn("## Open WebUI", acme_md)
        self.assertIn("Example IT checked", acme_md)
        self.assertNotIn("Baker", acme_md)

    def test_changes_since_previous(self):
        before = json.loads(json.dumps(self.report()))
        write(self.d, "acme/dify/docker/.env", STRONG_ENV)
        after = self.report(before)
        fixed = [x for x in after["changes"]["fixed"] if x["deployment"].startswith("Acme Dental / Dify")]
        self.assertTrue(fixed)
        self.assertEqual(after["changes"]["new"], [])
        self.assertIsNone(self.report()["changes"])

    def test_main_exit_codes_and_output(self):
        out = os.path.join(self.d, "out2")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(fc.main([self.fleet_path, "--out", out, "--checkers", HERE]), 0)
        self.assertIn("5 deployments", buf.getvalue())
        self.assertTrue(os.path.isfile(os.path.join(out, "fleet.json")))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fc.main([self.fleet_path, "--fail-on", "high", "--checkers", HERE]), 1)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fc.main([os.path.join(self.d, "nope.json")]), 2)
            self.assertEqual(fc.main([self.fleet_path, "--checkers", self.d]), 2)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fc.main([self.fleet_path, "--json", "--checkers", HERE])
        self.assertEqual(json.loads(buf.getvalue())["tool"], "ai-fleet-check")

    @unittest.skipUnless(os.path.isfile(os.path.join(HERE, "examples", "make_example.py")), "examples/ not present")
    def test_example_fleet(self):
        sys.path.insert(0, os.path.join(HERE, "examples"))
        import make_example
        demo = os.path.join(self.d, "demo")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(make_example.main([demo]), 0)
        with open(os.path.join(demo, "reports", "fleet.json"), encoding="utf-8") as f:
            report = json.load(f)
        self.assertEqual(report["errors"], 0)
        self.assertEqual(report["results"][0]["client"], "Harbor Accounting")
        self.assertGreaterEqual(report["results"][0]["counts"]["critical"], 1)
        lakeview = [r for r in report["results"] if r["client"] == "Lakeview Clinic"][0]
        self.assertEqual(lakeview["counts"]["critical"] + lakeview["counts"]["high"], 0)
        text = all_text(os.path.join(demo, "reports"))
        for value in ["difyai123456", "dify-sandbox"] + list(dhc.PUBLISHED_VALUES):
            self.assertNotIn(value, text)

    def test_slugs(self):
        self.assertEqual(fc.slug("Dana & Co"), "dana-co")
        self.assertEqual(fc.slug("***"), "client")


if __name__ == "__main__":
    unittest.main()
