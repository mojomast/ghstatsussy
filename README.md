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

## Notes

- `--include-private` includes private activity when the token allows it.
- Commit line additions/deletions come from repository commit detail endpoints and are best-effort for the selected window.
- If GitHub returns partial data or permissions are limited, the report includes warnings instead of failing hard.

## Project Layout

- `ghstats/cli.py` - CLI entrypoint
- `ghstats/config.py` - runtime settings and auth resolution
- `ghstats/github/client.py` - GitHub REST + GraphQL transport
- `ghstats/github/queries.py` - GraphQL query definitions
- `ghstats/service.py` - orchestration layer reusable by a future web app
- `ghstats/analytics/` - aggregation and metric calculation
- `ghstats/render/` - HTML rendering
- `ghstats/templates/report.html.j2` - report template
- `SPEC.md` - implementation spec and future direction

## Hosting Notes

- Reports are self-contained HTML files and can be hosted from any static file server
- The generated footer links to the source repository and to `https://ussy.host`
