# ai-fleet-check

For IT providers (MSPs) who run self-hosted AI apps such as [Dify](https://github.com/langgenius/dify) and [Open WebUI](https://github.com/open-webui/open-webui) for several small businesses: check every client's deployment files in one command, and get

- **one fleet summary**: which deployments need attention first, which problems repeat across clients (fix them once in your standard build), and what was fixed or is new since last month;
- **one plain-language report per client** that you can send as it is. It says what was checked and what to change, in order, and never contains a password or key.

It runs [dify-hardening-check](https://github.com/munimtechnologies/dify-hardening-check) and [openwebui-hardening-check](https://github.com/munimtechnologies/openwebui-hardening-check) on each deployment: published default passwords and keys still in use (including Dify 1.19's `docker/envs/**/*.defaults`), databases and sandboxes published to the network, risky settings and each project's known security advisories.

- **Offline and read-only.** It reads the files you already keep for each client (compose files, `.env`, `docker inspect` output, Kubernetes manifests). It never contacts a client's server.
- **Secret values are never printed**, in the summary, the client reports or the JSON. Only setting names such as `DB_PASSWORD` appear.
- Standard library Python 3, no install. Apache-2.0.

Made with AI agents for MV2 of Munim, Inc. Check data: the two checkers' own data dates (17 November 2026 for 0.1.3), shown at the top of every summary.

## Quick start

```sh
git clone https://github.com/munimtechnologies/ai-fleet-check && cd ai-fleet-check
python3 fleet_check.py /path/to/fleet.json --out reports/2026-11
```

`fleet.json` lists one entry per deployment. Paths are relative to `fleet.json`:

```json
{
  "provider": "Example IT",
  "deployments": [
    {"client": "Acme Dental", "app": "dify",      "path": "acme/dify/docker"},
    {"client": "Acme Dental", "app": "openwebui", "path": "acme/open-webui"},
    {"client": "Baker Law",   "app": "openwebui", "files": ["baker/compose.yml", "baker/.env"]},
    {"client": "Baker Law",   "app": "dify",      "path": "baker/dify/docker", "label": "staging"}
  ]
}
```

- `app`: `dify` or `openwebui` (`open-webui` also works).
- `path`: for Dify, its `docker/` folder (the checker reads `.env`, the compose file and `envs/**/*.defaults` / `*.env` in Dify's own order). For Open WebUI, a folder holding `.env`, a compose file or a pip install's `.webui_secret_key` (only its date is used).
- `files`: name files instead, for example `docker inspect` JSON or a Kubernetes manifest.
- `label`: tells two deployments of the same app for one client apart.

It writes:

| File | What's in it |
|---|---|
| `fleet.md` | The summary: a table of deployments, most urgent first; problems found on more than one deployment; changes since the previous check |
| `clients/<client>.md` | One report per client, all their deployments, findings in order with what to do and a source link for each |
| `fleet.json` | Everything above as JSON, for your PSA or ticketing tool; pass it back with `--previous` next month |

Monthly, with what changed:

```sh
python3 fleet_check.py fleet.json --out reports/2026-12 --previous reports/2026-11/fleet.json
```

Options:

| Option | What it does |
|---|---|
| `--out DIR` | Writes `fleet.md`, `fleet.json` and `clients/*.md`. Without it, only the text summary is printed. |
| `--previous FILE` | An earlier `fleet.json`: lists findings fixed and findings new since then, per deployment. |
| `--json` | Prints the fleet JSON instead of the text summary. |
| `--fail-on high` | Exit code 1 when any deployment has a finding this severe or worse, or couldn't be checked (for CI or a scheduled job). Default: `never`. |
| `--checkers DIR` | Where `dify_hardening_check.py` and `owui_hardening_check.py` are. Default: next to `fleet_check.py`. Use it to run newer checker releases. |

## How it ranks

A deployment that couldn't be checked (missing folder, unreadable file) comes first, so nothing silently drops out. Then deployments sort by their number of critical, then high, medium and low findings. A problem counts as "on more than one deployment" when the same setting (or the same check) fails on two or more of them; the most widespread come first.

## Limits

- It checks only the files you give it. A value set somewhere it can't see (a secrets manager, `${VAR}` from the shell, Kubernetes `valueFrom`) is treated as unknown, not as a problem.
- The checkers' advisory data is as of their data date. Update the two checker files (or point `--checkers` at newer ones) when Dify or Open WebUI publish new advisories.
- Not a scanner or a certification. This is general technical information.

## Written review

MV2 of Munim, Inc. also writes a review of a self-hosted AI server: what's exposed, risky or out of date, what to fix first, with exact commands, and one follow-up check by email. It's made with AI agents and is general technical information. See a [sample report](https://munimv2.github.io/sample-report.html).

- **$199 per shared server** (Dify, Open WebUI, Ollama or n8n used by a team), or up to 5 machines: [pay on Stripe](https://buy.stripe.com/aFabJ0foU2vw6Jo8o13Ru01).
- **$49, one machine:** [pay on Stripe](https://buy.stripe.com/5kQcN43Gcfii6Jo47L3Ru00).

After paying, email munimversion2@gmail.com the client's report or the `--json` output for that deployment (both are free of secret values), the app version and OS, and what the server is used for. The review arrives within 48 hours. MV2 never asks for passwords, keys or remote access.

## For coding agents

[`skills/ai-fleet-check/SKILL.md`](skills/ai-fleet-check/SKILL.md) tells an agent how to build `fleet.json` from a folder of client deployments, run the check and summarise the results without printing secret values:

```sh
npx skills add munimtechnologies/ai-fleet-check
```

## Development

```sh
python3 -m unittest -v test_fleet_check.py
```

`dify_hardening_check.py` and `owui_hardening_check.py` are copies of the 0.1.3 releases of the two checkers (same licence), kept here so the tool works after one clone.

Apache-2.0 licensed. Dify is a trademark of LangGenius, Inc.; Open WebUI is a trademark of its owners. This project isn't affiliated with or endorsed by either.
