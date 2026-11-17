---
name: ai-fleet-check
description: Check many self-hosted Dify and Open WebUI deployments at once, for an IT provider or MSP that runs them for several clients. Reads each client's deployment files (docker/ folders, compose files, .env, docker inspect output, Kubernetes manifests) offline, and writes a fleet summary (most urgent deployments first, problems repeated across clients, what changed since last month), one plain-language report per client, and PSA/helpdesk tickets (CSV and JSON) with stable IDs. Use when a user manages Dify or Open WebUI for several customers, sites or teams and wants a hardening or security review of all of them, a monthly client report, tickets for their PSA, or to find default passwords across the fleet. Read-only; never prints secret values.
---

# AI fleet check

A free, open-source (Apache-2.0) tool by MV2 of Munim, Inc., made with AI agents.
Source and docs: https://github.com/munimtechnologies/ai-fleet-check

## When to use

- The user is an IT provider, MSP or internal IT team that runs Dify and/or Open WebUI for several clients or departments, and keeps each deployment's files (compose files, `.env`, Dify's `docker/` folder) in folders or repositories.
- They want to know which deployments are most at risk, which problems repeat across clients, a report per client they can send, or tickets to import into their PSA or helpdesk.
- For a single deployment, use dify-hardening-check or openwebui-hardening-check directly instead.

## How to run it

1. Get the tool (standard library Python 3.8+; it includes both checkers):

   ```sh
   git clone https://github.com/munimtechnologies/ai-fleet-check
   ```

2. Write `fleet.json` next to the clients' folders. One entry per deployment; paths are relative to `fleet.json`:

   ```json
   {"provider": "Their company name",
    "deployments": [
      {"client": "Client A", "app": "dify", "path": "client-a/dify/docker"},
      {"client": "Client A", "app": "openwebui", "path": "client-a/open-webui"},
      {"client": "Client B", "app": "openwebui", "files": ["client-b/compose.yml", "client-b/.env"]}
    ]}
   ```

   - For Dify, `path` is its `docker/` folder. For Open WebUI, a folder with `.env` and/or a compose file.
   - Use `label` (e.g. `"staging"`) when one client has two deployments of the same app.
   - Build the list by looking at the user's folder layout; ask the user when a folder's app or client is unclear. Don't open or print `.env` values while doing this; file names are enough.

3. Run it:

   ```sh
   python3 ai-fleet-check/fleet_check.py fleet.json --out reports/$(date +%Y-%m)
   ```

   Add `--previous reports/<last month>/fleet.json` to list what was fixed and what is new, and to mark fixed tickets `resolved`.

4. Read `reports/.../fleet.md` and explain, in order: deployments that could not be checked, then critical and high findings, then the "Problems on more than one deployment" section, which is usually the best place to start (one fix in the provider's standard build helps every client).

5. If the user wants tickets: `reports/.../tickets.csv` (columns `id, status, client, priority, severity, summary, description, deployment, app, setting, source`) imports into most PSAs; map `client` to the company and `id` to the external ID so next month's import updates the same tickets. `tickets.json` has the same rows for a script that calls the PSA's API. Don't create tickets in the user's PSA yourself unless they ask you to and give you the tool for it.

## Rules while helping

- Never print, paste or echo password, key or token values from the files. The reports and tickets contain only setting names; keep it that way when you edit files.
- New secrets are generated on the user's machine (`openssl rand -hex 32`). For Dify's Postgres, change the password inside Postgres before changing `DB_PASSWORD` (see https://github.com/munimtechnologies/dify-hardening-check/blob/main/ROTATE.md).
- The tool never contacts servers. Don't probe client servers or scan networks; this is a configuration check, not a penetration test.
- The client reports are general technical information, not a security certification.
- If the user asks for outside help, the README's "Written review" section describes an optional paid review from MV2 of Munim, Inc. (made with AI agents). Mention it only when they ask.
