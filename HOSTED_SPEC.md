# Hosted ghstatsussy Specification

## Goal

Turn `ghstatsussy` into a hosted web app where a user can:

- sign in with GitHub OAuth
- generate a report from their own GitHub activity
- receive a shareable link for the generated report
- refresh or regenerate that report later
- export the stored report as PDF, PNG, standalone HTML, or markdown
- optionally publish markdown to a GitHub profile README through a repo-scoped GitHub App flow

## Product Shape

- FastAPI web app
- GitHub OAuth for authentication
- persistent storage for users, report jobs, and report snapshots
- self-hosted HTML report artifacts stored on disk for now
- public share links served from stored snapshots, not from live GitHub calls
- privacy-first retention: HTML only by default, metadata only when the user opts in
- derived exports generated from stored snapshot and presentation state only
- GitHub profile README publishing guarded by diff preview and explicit confirmation

## Reuse Strategy

The existing CLI core remains the source of truth for:

- GitHub API fetching
- analytics
- HTML rendering

The hosted layer adds:

- OAuth and sessions
- persistence
- report ownership and visibility
- shareable routes

## MVP Routes

- `GET /` - landing page or dashboard redirect
- `GET /healthz` - health check
- `GET /auth/github/login` - begin GitHub OAuth flow
- `GET /auth/github/callback` - OAuth callback, user creation, session setup
- `POST /auth/logout` - clear session
- `GET /dashboard` - signed-in dashboard
- `POST /dashboard/reports` - generate a report from the dashboard form
- `GET /dashboard/reports/{report_id}` - owner report detail page
- `GET /api/me` - current user JSON
- `GET /api/reports` - current user reports JSON
- `POST /api/reports` - create report JSON endpoint
- `GET /api/reports/{report_id}` - report detail JSON
- `POST /api/reports/{report_id}/refresh` - regenerate the report
- `POST /api/reports/{report_id}/exports` - queue an export artifact job
- `GET /api/reports/{report_id}/exports` - list export artifacts
- `GET /api/reports/{report_id}/exports/{export_id}` - export detail
- `GET /api/reports/{report_id}/exports/{export_id}/download` - owner-only artifact download
- `POST /api/reports/{report_id}/markdown` - generate markdown preview/body
- `POST /api/reports/{report_id}/markdown/preview` - generate markdown preview/body
- `GET /api/github/profile-readme/status` - current GitHub App publish status
- `POST /api/github/profile-readme/connect` - save repo-scoped install metadata
- `GET /api/github/profile-readme/current` - fetch current profile README
- `POST /api/reports/{report_id}/profile-readme/diff` - preview README diff
- `POST /api/reports/{report_id}/profile-readme/publish` - publish after explicit confirmation
- `GET /r/{slug}` - public or unlisted share page

## Persistence

### Users

- GitHub identity
- encrypted OAuth token
- profile basics for the dashboard

### Reports

- owner id
- title
- time window
- private/public visibility
- share slug
- username slug for `username.ghstats.ussyco.de`
- status and timestamps
- expiry time
- metadata retention flag

### Snapshots

- version number
- rendered HTML path
- JSON artifact path only when metadata retention is enabled
- private/restricted metadata

### Jobs

- queued/running/succeeded/failed status
- generation vs refresh type
- export jobs with snapshot-bound artifact metadata
- timestamps and retry count

### Export artifacts

- export type (`pdf`, `png`, `html`, `markdown`)
- source snapshot id
- owner id
- presentation hash and bounded options
- artifact path, MIME type, and byte size

### GitHub profile publish connection

- target profile repo owner/name
- GitHub App installation id
- last publish commit SHA/time

## Security Notes

- OAuth tokens stay server-side only
- session cookie is signed and HTTP-only
- OAuth state is stored in session and verified on callback
- public share routes only serve stored HTML snapshots
- export routes use stored snapshot data and do not refetch GitHub just to change format
- private reports cannot be shared unless visibility is changed
- `include_private` reports are forced to remain private in this MVP
- final hosted HTML should contain only derived stats, not raw GitHub API payloads
- private-report exports stay owner-only and are not exposed through public artifact URLs
- profile publishing uses a GitHub App installed on one profile repo, not broad OAuth write scopes and not stored PATs
- README publishing must show a diff preview before any write

## Current MVP Tradeoffs

- uses local disk for artifacts instead of S3
- uses SQLAlchemy table creation instead of full migrations
- currently processes queued jobs in-process for the web path, but also includes a worker loop for separation
- keeps refresh simple for now; queue-based workers can come later
- standalone HTML portability currently comes from freezing charts and stripping remote font/runtime dependencies
- PDF and PNG require Playwright Chromium runtime availability on the host or worker
- production worker loops should recover stale `running` jobs after interrupted deploys or restarts so queued jobs are not blocked behind abandoned work
- production queue claims must be atomic so multiple workers can share the same job table without double-processing the same queued item

## Data Coverage Notes

- canonical summary cards still inherit some GitHub attribution semantics, especially for `totalCommitContributions`
- detailed commit scans now broaden coverage by matching both author and committer identities, including common GitHub noreply aliases
- detailed commit scans now enumerate repository branches instead of assuming the default branch is the only source of relevant commits
- repository discovery should paginate through pushed repositories so newer repos are not silently dropped after the first page
- when configured scan caps or API limits prevent exhaustive coverage, the product should warn rather than imply exact completeness

## Frontend Preview Mode

The app also supports a preview-only mode for isolated frontend work:

- enabled with `PREVIEW_MODE=1`
- bypasses GitHub auth by returning a synthetic preview user from the existing session dependency
- seeds dashboard and report detail pages with deterministic sample report data
- seeds export and profile publishing surfaces with deterministic preview responses
- intended for non-production Docker stacks only

## Future Evolution

- dedicated background workers for large report runs
- Postgres + Alembic migrations
- encrypted token rotation and key management
- scheduled refresh jobs
- per-user vanity links or subdomains
- organization/team reports
- scheduled README republish and PR-based publish mode for protected profile repos
