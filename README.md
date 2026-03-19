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
- Hosted FastAPI app with GitHub OAuth, share links, and instant presentation controls
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
- `cyberpunk` - Cyberpunk Neon
- `glassmorphism` - Frosted Glass
- `brutalism` - Neo-Brutalism
- `retro_os` - Classic OS Window
- `holo` - Holographic Foil
- `synthwave` - Synthwave Horizon
- `paper` - Ink on Paper
- `monochrome` - Strict Monochrome
- `matrix` - Digital Rain
- `liquid` - Liquid Morph

## Notes

- `--include-private` includes private activity when the token allows it.
- Commit line additions/deletions come from repository commit detail endpoints and are best-effort for the selected window.
- If GitHub returns partial data or permissions are limited, the report includes warnings instead of failing hard.

## Hosted App

`ghstatsussy` now includes a FastAPI hosted-app scaffold so users can sign in with GitHub OAuth, generate a report on the server, and get a shareable report URL.

Hosted app pieces live in `ghstats/web/` and reuse the same fetch/analytics/render core as the CLI.

Live hosted demo:

- app: `https://ghstats.ussyco.de`
- public gallery: `https://ghstats.ussyco.de/gallery`

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
- lets report owners hot-swap themes, visible sections, and selected copy without rerunning the data job
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
- invalid public-expiry submissions now stay on the dashboard with a clear inline validation message instead of surfacing a 500 error
- title input is length-limited and normalized server-side
- server validation rejects invalid template keys, invalid windows, overlong public expiry, and unsafe private/public combinations
- report, job, and detail routes now use stricter typed identifiers on the server side
- **Robust Error Handling**: The background worker now gracefully skips completely empty git repositories instead of throwing an API conflict error and failing the job.
- **Broader Commit Coverage**: Detailed commit scans now walk repository branches, match both author and committer identities, and recognize GitHub noreply aliases so agent-assisted and harness-assisted commits are less likely to disappear from short windows.
- **Broader Repository Coverage**: Viewer repository discovery now paginates beyond the first GraphQL page so newer repositories are less likely to be omitted from long-window reports.
- **Smarter Retry Behavior**: The GitHub client now backs off on `403`/`429` rate-limit responses in addition to transient `5xx` errors.

### Coverage caveats

- the top-level `Total commits` card still reflects GitHub's own attributed commit contribution count, which may differ from the detailed per-commit scan for rebased, bot-authored, or otherwise reattributed work
- detailed commit charts and streaks now use commit time (`committer.date`) rather than author time to better reflect when work actually landed
- repository cards now favor recently active repositories so fresh work is easier to see in long windows like `365d`
- very large accounts can still hit configured safety caps for branches, repositories, and detailed commits; when that happens the report surfaces warnings instead of silently pretending coverage is complete

### Behavioral Insights & Fun Facts

Added dynamic pattern recognition to user activity, surfacing highlights such as:
- **Night Owl** / **Morning Person** (based on UTC commit hours)
- **Weekend Warrior** (if weekend output surpasses weekdays)
- **Language Polyglot** (contributing to 5+ programming languages)
- **Fastest Sprint** (max commits in a single day)
- **Consistent Contributor** (streak tracking of 14+ days)

### Public Gallery & Themed Templates

Added a **Public Gallery** route (`/gallery`) allowing visitors to browse reports generated with `public` visibility.

Hosted reports now support persisted `presentation_config` edits so owners can switch themes, toggle sections, and adjust selected copy instantly from the report detail page.

Users can choose from 20 report themes spanning the original structural set plus 10 radical CSS overhauls:
- `orbital`: Telemetry-heavy, dark-ops mission control terminal HUD.
- `gallery`: Asymmetric, color-blocked poster/art exhibit.
- `ledger`: Editorial, classic multi-column newspaper layout.
- `transit`: Neon subway map aesthetic with overlapping routes.
- `archive`: Curated, classical museum-artifact wall.
- `scrapbook`: Chaotic, rotated elements with punk zine energy.
- `fieldnotes`: Rugged, grid-ruled handwritten notebook design.
- `signalroom`: Glowing green phosphorescent hacker terminal with scanlines.
- `tapearchive`: Industrial, modular tape reel and index card interface.
- `default`: Polished, frosted-glass modern dashboard.
- `cyberpunk`: Neon CRT glitch aesthetic with angular terminal panels.
- `glassmorphism`: Frosted translucent cards over blurred color fields.
- `brutalism`: Loud, flat, poster-like blocks with oversized typography.
- `retro_os`: Windows-95-style interface chrome and beveled widgets.
- `holo`: Holographic glow surfaces with scanlines and iridescent effects.
- `synthwave`: Outrun sunset grid with neon cyan and magenta accents.
- `paper`: Notebook paper, sticky notes, and hand-drawn print vibes.
- `monochrome`: Harsh black-and-white editorial layout with geometric contrast.
- `matrix`: Terminal-green digital rain with hacker-console framing.
- `liquid`: Organic morphing blobs and glossy fluid gradients.

### Frontend Preview Docker Stack

For frontend work, use the isolated preview stack instead of the production compose project:

```bash
docker compose -f docker-compose.preview.yml up -d --build
```

- serves a preview-only app on `http://127.0.0.1:8011`
- enables `PREVIEW_MODE=1` so dashboard/report pages render with seeded sample content and no GitHub auth
- keeps its own SQLite database and artifacts under `./preview_artifacts`
- does not touch the production `web` / `worker` containers or `./web_artifacts`

## Docker Deployment (Production)

To gracefully deploy `ghstatsussy` in a containerized environment (which encapsulates both the FastAPI web server and the background worker):

1. **Clone and Prepare**
   ```bash
   git clone https://github.com/mojomast/ghstatsussy.git
   cd ghstatsussy
   ```

2. **Configure Environment**
   Create a `.env` file in the root of the project with your secrets:
   ```env
   APP_SECRET_KEY=your_secure_random_string
   APP_BASE_URL=https://ghstats.yourdomain.com
   GITHUB_CLIENT_ID=your_oauth_client_id
   GITHUB_CLIENT_SECRET=your_oauth_client_secret
   GHSTATS_SUBDOMAIN_BASE=ghstats.yourdomain.com
   ALLOW_SAMPLE_REPORTS=0
   ```

3. **Run with Docker Compose**
   ```bash
   docker compose up -d --build
   ```
   This will spin up two containers (`web` and `worker`) that share a mounted `./web_artifacts` volume for the SQLite database and generated HTML files. The web app exposes port `8001` to `127.0.0.1`, ready to be reverse-proxied by Nginx or Caddy.

4. **Migrating from Systemd**
   If you are moving an existing bare-metal systemd deployment to Docker:
   ```bash
   # 1. Stop existing services
   sudo systemctl stop ghstatsussy-web ghstatsussy-worker
   sudo systemctl disable ghstatsussy-web ghstatsussy-worker
   
   # 2. Copy your existing environment variables
   sudo cp /etc/ghstatsussy.env .env
   sudo chown $USER:$USER .env
   
   # 3. Start docker-compose
   docker compose up -d --build
   ```

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
- `ghstats/templates/report_base.html.j2` - shared report shell
- `ghstats/templates/report_*.html.j2` - theme templates and overrides
- `ghstats/web/` - FastAPI hosted app, OAuth, persistence, share links
- `SPEC.md` - implementation spec and future direction
- `HOSTED_SPEC.md` - hosted app architecture and roadmap

## Hosting Notes

- Reports are self-contained HTML files and can be hosted from any static file server
- The generated footer links to the source repository and to `https://ussy.host`
