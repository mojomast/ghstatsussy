# ghstats Specification

## Goal

Build a CLI-first Python application that inspects the activity of the currently authenticated GitHub user and outputs a visually rich HTML infographic report.

The project must keep GitHub data fetching, analytics, and rendering decoupled so the core can later be reused by a web app using GitHub OAuth.

## Product Scope

- Input: current authenticated GitHub user
- Auth: `GITHUB_TOKEN` or `GH_TOKEN`
- Output: self-contained HTML report, optional JSON export
- Windowing: relative time range via `--since` such as `7d`, `30d`, `12w`, `6m`
- Presentation: responsive report with stat cards, charts, repo insights, and highlights

## Architecture

### CLI Layer

- Parses arguments with `typer`
- Resolves config and output paths
- Calls a service object
- Saves HTML and optional JSON
- Can optionally open the generated report in a browser

### Service Layer

- Owns the end-to-end data flow
- Depends on a token/auth abstraction, not directly on environment variables
- Coordinates GitHub fetches, normalization, analytics, and rendering
- Designed to be reusable from a future Flask/FastAPI route handler

### Data Layer

- `GitHubClient` wraps REST and GraphQL calls
- GraphQL is preferred for:
  - viewer profile
  - contribution calendar
  - contribution repo buckets
  - PR and issue search results
  - repo language metadata
- REST is used for:
  - per-repo commit listing
  - per-commit additions/deletions stats
- Handles pagination, retryable failures, and rate-limit messaging

### Analytics Layer

- Normalizes raw API data into internal dataclasses
- Computes:
  - total commits
  - commits per day
  - lines added/deleted total and by day
  - PRs opened and merged
  - issues opened
  - repos contributed to
  - most active weekday and hour
  - longest/current commit streak
  - top languages and repositories
  - productive-day and largest-commit highlights

### Presentation Layer

- Uses Jinja2 for HTML generation
- Embeds report data into the template
- Uses Chart.js via CDN for charts
- Uses CSS and a custom heatmap grid for the infographic layout

## Data Flow

1. Parse CLI options
2. Resolve token and time window
3. Fetch viewer summary and contributions via GraphQL
4. Fetch authored PRs/issues via GraphQL search
5. Fetch owned and contributed repos via GraphQL
6. Fetch commit history and commit stats via REST
7. Normalize into internal models
8. Aggregate and compute metrics
9. Render HTML and save output
10. Optionally export raw JSON and open the report in a browser

## Key Design Decisions

- Keep CLI concerns outside core analytics and service modules
- Keep GitHub auth swappable for future OAuth support
- Return warnings for partial data instead of crashing when possible
- Precompute display-ready context objects before rendering so templates stay simple
- Support `--sample-data` to demonstrate output without API access

## Future Evolution

- Replace token auth with OAuth device/web flow
- Expose the service from FastAPI or Flask routes
- Add persistent response caching
- Add scheduled report generation and historical comparisons
- Add a report comparison mode between two time windows
