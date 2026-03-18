# Hosted ghstatsussy Specification

## Goal

Turn `ghstatsussy` into a hosted web app where a user can:

- sign in with GitHub OAuth
- generate a report from their own GitHub activity
- receive a shareable link for the generated report
- refresh or regenerate that report later

## Product Shape

- FastAPI web app
- GitHub OAuth for authentication
- persistent storage for users, report jobs, and report snapshots
- self-hosted HTML report artifacts stored on disk for now
- public share links served from stored snapshots, not from live GitHub calls
- privacy-first retention: HTML only by default, metadata only when the user opts in

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
- timestamps and retry count

## Security Notes

- OAuth tokens stay server-side only
- session cookie is signed and HTTP-only
- OAuth state is stored in session and verified on callback
- public share routes only serve stored HTML snapshots
- private reports cannot be shared unless visibility is changed
- `include_private` reports are forced to remain private in this MVP
- final hosted HTML should contain only derived stats, not raw GitHub API payloads

## Current MVP Tradeoffs

- uses local disk for artifacts instead of S3
- uses SQLAlchemy table creation instead of full migrations
- currently processes queued jobs in-process for the web path, but also includes a worker loop for separation
- keeps refresh simple for now; queue-based workers can come later

## Future Evolution

- dedicated background workers for large report runs
- Postgres + Alembic migrations
- encrypted token rotation and key management
- scheduled refresh jobs
- per-user vanity links or subdomains
- organization/team reports
