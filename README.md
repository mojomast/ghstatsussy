# ghstatsussy

`ghstats` is a Python 3.11+ CLI that analyzes the GitHub activity of the currently authenticated user and renders a polished HTML infographic report.

It is built CLI-first, but the internal architecture keeps data collection, analytics, and presentation separate so the same backend can later power a Flask or FastAPI app with GitHub OAuth.

## Features

- GitHub token auth via `GITHUB_TOKEN` or `GH_TOKEN`
- Time-windowed activity analysis with `7d`, `30d`, `12w`, `6m`, and `1y` style ranges
- Hybrid GitHub API approach: GraphQL for contribution and aggregate data, REST for commit details and line stats
- Single-file HTML report with embedded CSS and Chart.js charts
- Analytics for commits, LOC churn, PRs, issues, language mix, repo insights, streaks, and fun facts
- Optional raw JSON export
- Sample-data mode for local previewing without a token
- Generated reports include links back to the project repo and the ussyverse at `https://ussy.host`

## Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Optional editable install with the console script:

```bash
python -m pip install -e .
```

## Usage

### Auth options

You can authenticate in any of these ways:

- `GITHUB_TOKEN`
- `GH_TOKEN`
- `GH_ACCESS_TOKEN`
- `--token <token>`

If you already use the GitHub CLI, you can reuse its auth session without manually copying a token:

```bash
export GH_ACCESS_TOKEN="$(gh auth token)"
ghstats --since 30d --output report.html
```

Pick a visual report template:

```bash
ghstats --since 90d --template orbital --output report.html
```

If installed as a package:

```bash
export GITHUB_TOKEN=your_token_here
ghstats --since 30d
ghstats --since 12w --output report.html
ghstats --since 6m --include-private --json-output activity.json
```

Without installing the console script:

```bash
export GITHUB_TOKEN=your_token_here
python -m ghstats --since 30d --output report.html
```

Generate a demo report without GitHub API access:

```bash
python -m ghstats --sample-data --output examples/sample_report.html
```

Generate a live report using your authenticated `gh` session:

```bash
GH_ACCESS_TOKEN="$(gh auth token)" python -m ghstats --since 90d --output report.html
```

Available templates:

- `default` - Signal Glass
- `ledger` - Maintainer's Ledger
- `transit` - Merge Line Transit Map
- `archive` - Archive Exhibit
- `scrapbook` - Indie Dev Scrapbook
- `orbital` - Orbital Telemetry Brief
- `fieldnotes` - Field Notes
- `signalroom` - Signal Room
- `gallery` - Gallery Wall
- `tapearchive` - Tape Archive

## Notes

- `--include-private` includes private activity when the token allows it.
- Commit line additions/deletions come from repository commit detail endpoints and are best-effort for the selected window.
- If GitHub returns partial data or permissions are limited, the report includes warnings instead of failing hard.

## Hosted App

`ghstatsussy` now includes a FastAPI hosted-app scaffold so users can sign in with GitHub OAuth, generate a report on the server, and get a shareable report URL.

Hosted app pieces live in `ghstats/web/` and reuse the same fetch/analytics/render core as the CLI.

### Hosted app environment

```bash
export APP_SECRET_KEY="change-me"
export GITHUB_CLIENT_ID="your_github_oauth_app_client_id"
export GITHUB_CLIENT_SECRET="your_github_oauth_app_client_secret"
export APP_BASE_URL="http://127.0.0.1:8001"
```

Optional:

```bash
export DATABASE_URL="sqlite:///./web_artifacts/ghstatsussy.db"
export REPORT_STORAGE_DIR="./web_artifacts"
export ALLOW_SAMPLE_REPORTS=1
```

### Run the hosted app

```bash
ghstats-web
```

Or without installing the console script:

```bash
python -m uvicorn ghstats.web.app:app --host 127.0.0.1 --port 8001 --reload
```

### GitHub OAuth callback URL

Create a GitHub OAuth App and set its callback URL to:

```text
http://127.0.0.1:8001/auth/github/callback
```

Replace the host with your production URL when you deploy it.

### Hosted app behavior

- signs users in with GitHub OAuth
- stores the GitHub token server-side only
- queues report generation jobs instead of doing long work in the browser
- lets the user generate reports for windows like `30d`, `12w`, and `6m`
- persists HTML artifacts by default and stores JSON metadata only when the user opts in
- serves public or unlisted report links at `/r/{slug}`
- supports per-user subdomain-style URLs like `username.ghstats.ussyco.de`
- keeps `include_private` reports private in this MVP

### Privacy-first hosted posture

- default retention is the final hosted HTML page only
- raw GitHub API responses are not stored
- report JSON/metadata retention is opt-in
- background workers fetch GitHub data, render the page, then keep only the configured artifacts
- reports have an expiry window so hosted pages can age out automatically
- if you want true no-retention refreshes, disable metadata storage and require the user to regenerate from a live OAuth session

### Input hardening

- hosted report creation now uses fixed dropdowns for time window, visibility, and expiry wherever practical
- the dashboard template chooser is now a visual picker with palette chips, style badges, and stronger dark-mode form contrast
- title input is length-limited and normalized server-side
- server validation rejects invalid template keys, invalid windows, overlong public expiry, and unsafe private/public combinations
- report, job, and detail routes now use stricter typed identifiers on the server side

### Production hostnames

- dashboard/app host: `ghstats.ussyco.de`
- public share host pattern: `username.ghstats.ussyco.de`

Important TLS note:

- the existing `*.ussyco.de` certificate can cover `ghstats.ussyco.de`
- it cannot cover nested hosts like `username.ghstats.ussyco.de`
- for per-user subdomains you need a dedicated certificate for:
  - `ghstats.ussyco.de`
  - `*.ghstats.ussyco.de`

Deployment templates are included in `examples/`:

- `examples/ghstats.ussyco.de.nginx.conf`
- `examples/wildcard-ghstats.ussyco.de.nginx.conf`
- `examples/ghstatsussy-web.service`
- `examples/ghstatsussy-worker.service`
- `examples/certbot-ghstats-command.txt`

## Project Layout

- `ghstats/cli.py` - CLI entrypoint
- `ghstats/config.py` - runtime settings and auth resolution
- `ghstats/github/client.py` - GitHub REST + GraphQL transport
- `ghstats/github/queries.py` - GraphQL query definitions
- `ghstats/service.py` - orchestration layer reusable by a future web app
- `ghstats/analytics/` - aggregation and metric calculation
- `ghstats/render/` - HTML rendering
- `ghstats/templates/report.html.j2` - report template
- `ghstats/web/` - FastAPI hosted app, OAuth, persistence, share links
- `SPEC.md` - implementation spec and future direction
- `HOSTED_SPEC.md` - hosted app architecture and roadmap

## Hosting Notes

- Reports are self-contained HTML files and can be hosted from any static file server
- The generated footer links to the source repository and to `https://ussy.host`
