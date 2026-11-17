#!/usr/bin/env python3
"""Builds a made-up fleet of three clients (files only, nothing runs) and checks it,
so you can see what ai-fleet-check writes before pointing it at real deployments.

    python3 examples/make_example.py /tmp/demo-fleet
    # then open /tmp/demo-fleet/reports/fleet.md and /tmp/demo-fleet/reports/clients/*.md

The client names are invented. The Dify files copy the layout of Dify 1.19's docker/
folder, whose published default values are public (they are what the check looks for).
Apache-2.0. Made with AI agents for MV2 of Munim, Inc.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import dify_hardening_check as dhc  # noqa: E402
import fleet_check  # noqa: E402

DIFY_DEFAULTS = {
    os.path.join("envs", "databases", "db-postgres.defaults"):
        "DB_USERNAME=${DB_USERNAME:-postgres}\n"
        "DB_PASSWORD=${DB_PASSWORD:-difyai123456}\nPOSTGRES_PASSWORD=${DB_PASSWORD:-difyai123456}\n",
    os.path.join("envs", "core-services", "plugin-daemon.defaults"):
        "SERVER_KEY=${PLUGIN_DAEMON_KEY:-%s}\n" % dhc.PUBLISHED_KEYS["PLUGIN_DAEMON_KEY"],
    os.path.join("envs", "core-services", "sandbox.defaults"):
        "SANDBOX_API_KEY=${SANDBOX_API_KEY:-dify-sandbox}\nAPI_KEY=${SANDBOX_API_KEY:-dify-sandbox}\n",
}

FILES = {
    # A Dify 1.19 install whose docker/.env was copied unchanged from .env.example.
    "northside-dental/dify/docker/.env": "COMPOSE_PROFILES=weaviate,postgresql\nDIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN=\n",
    "northside-dental/dify/docker/docker-compose.yaml":
        "services:\n  api:\n    image: langgenius/dify-api:1.19.0\n",
    # An older Open WebUI with sign-up open and the port on every interface.
    "northside-dental/open-webui/docker-compose.yml":
        "services:\n  open-webui:\n    image: ghcr.io/open-webui/open-webui:v0.12.0\n    ports:\n      - 3000:8080\n"
        "    environment:\n      - 'ENABLE_SIGNUP=true'\n      - 'DEFAULT_USER_ROLE=user'\n",
    # Same Dify build at a second client, plus the dev middleware stack published to the network.
    "harbor-accounting/dify/docker/.env": "COMPOSE_PROFILES=weaviate,postgresql\nDIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN=\n",
    "harbor-accounting/dify/docker/docker-compose.yaml":
        "services:\n  api:\n    image: langgenius/dify-api:1.17.1\n",
    "harbor-accounting/dify/docker/docker-compose.middleware.yaml":
        "services:\n  db_postgres:\n    ports:\n      - \"${EXPOSE_POSTGRES_PORT:-5432}:5432\"\n",
    # A third client that already replaced the defaults and pinned a current release.
    "lakeview-clinic/open-webui/docker-compose.yml":
        "services:\n  open-webui:\n    image: ghcr.io/open-webui/open-webui:v0.13.3\n    ports:\n      - 127.0.0.1:3000:8080\n"
        "    environment:\n      - 'ENABLE_SIGNUP=false'\n      - 'CORS_ALLOW_ORIGIN=https://chat.lakeview.example'\n"
        "      - 'WEBUI_URL=https://chat.lakeview.example'\n",
    "lakeview-clinic/open-webui/.env": "WEBUI_SECRET_KEY=${WEBUI_SECRET_KEY_FROM_VAULT}\n",
}

FLEET = {
    "provider": "Example IT",
    "deployments": [
        {"client": "Northside Dental", "app": "dify", "path": "northside-dental/dify/docker"},
        {"client": "Northside Dental", "app": "openwebui", "path": "northside-dental/open-webui"},
        {"client": "Harbor Accounting", "app": "dify",
         "files": ["harbor-accounting/dify/docker", "harbor-accounting/dify/docker/docker-compose.middleware.yaml"]},
        {"client": "Lakeview Clinic", "app": "openwebui", "path": "lakeview-clinic/open-webui"},
    ],
}


def build(base):
    for client in ("northside-dental", "harbor-accounting"):
        for rel, text in DIFY_DEFAULTS.items():
            FILES["%s/dify/docker/%s" % (client, rel.replace(os.sep, "/"))] = text
    for rel, text in FILES.items():
        path = os.path.join(base, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    path = os.path.join(base, "fleet.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(FLEET, f, indent=2)
    return path


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: make_example.py OUT_DIR", file=sys.stderr)
        return 2
    fleet = build(argv[0])
    return fleet_check.main([fleet, "--out", os.path.join(argv[0], "reports"), "--checkers", ROOT])


if __name__ == "__main__":
    sys.exit(main())
