# Export And Profile Publishing Specification

## Goal

Extend `ghstatsussy` so a report can be exported and reused outside the hosted app, and so a user can transform report data into a polished GitHub profile README workflow.

The feature set should support:

- PDF export for polished sharing and archival
- image export for screenshots, social posting, and embeds
- standalone single-file HTML export for portable hosting or offline viewing
- markdown export for README-style reuse
- optional GitHub profile README publishing from inside the hosted app

## Product Goals

- Preserve the existing hosted report as the canonical rich artifact.
- Make exports visually faithful to the rendered report, not a lossy approximation.
- Keep private/public safety rules unchanged.
- Keep export generation deterministic and snapshot-based.
- Provide a markdown mode that captures the essence of the report in GitHub-native form.
- Make GitHub publishing explicit, previewable, and least-privilege by design.

## Non-goals

- Arbitrary file publishing to any repository path
- Full CMS/blog export tooling
- Rich WYSIWYG markdown editing
- Client-side-only export generation as the primary path
- Direct mutation of GitHub content without user preview/confirmation
- A fake "README-only" permission model that GitHub does not actually provide

## Core Principles

### Snapshot-first architecture

- Exports must be generated from a stored immutable report snapshot or snapshot-equivalent render context.
- Export generation must not refetch live GitHub data.
- Presentation-only changes should be exportable without rerunning analytics.
- Export cache keys must include immutable data snapshot identity plus presentation identity.

### Privacy and safety

- Export eligibility follows the same visibility and `include_private` rules as hosted reports.
- Private report exports remain owner-only and must never be exposed through public URLs.
- Export rendering must use trusted internal inputs only, never arbitrary URLs.
- Markdown export must use only sanitized report data.

### Fidelity over cleverness

- Browser rendering is the source of truth for PDF/image fidelity.
- Standalone HTML should be a frozen artifact, not a pointer to external runtime assets.
- Markdown is a companion representation, not a visual clone.

## Export Types

### 1. PDF export

Use case:

- polished shareable document
- recruiter/client/stakeholder handoff
- archive or print-friendly export

Requirements:

- generated server-side via headless browser rendering
- print CSS support for sane pagination and margins
- render current presentation config and selected theme
- support owner-only generation for private reports
- cached by snapshot + presentation hash + paper options

### 2. Image export

Use case:

- social card or portfolio screenshot
- quick visual sharing
- embedding in docs or decks

Requirements:

- generated server-side via headless browser screenshot
- phase 1 supports PNG
- add size guards for extremely tall pages
- for oversized reports, product can recommend PDF instead of PNG

### 3. Standalone single-file HTML export

Use case:

- portable artifact that works offline
- user-hosted static copy
- attachable/shareable HTML deliverable

Requirements:

- all required CSS inlined
- no runtime dependency on remote CDN assets
- charts frozen into image/canvas-safe representation so the file remains portable
- should open directly from disk and still render correctly
- current presentation config baked into the artifact

### 4. Markdown export

Use case:

- GitHub profile README
- personal site markdown block
- repo `README.md` summary section

Requirements:

- generated from sanitized report data, not OCR or HTML scraping
- support at least two presets:
  - `profile_readme`
  - `summary_markdown`
- user can opt into compact or expanded section sets
- markdown should include links back to the hosted report when appropriate
- markdown should degrade gracefully when data sections are unavailable

## Recommended Technical Architecture

## Rendering engine

- Use Playwright + Chromium for PDF and image export.
- Keep browser rendering in a dedicated export service or worker process.
- Do not use `wkhtmltopdf` or WeasyPrint as the primary implementation for this repo.

Why:

- the app already renders complex HTML/CSS themes and Chart.js charts
- browser rendering provides the best fidelity with the least theme-specific rewrite work
- the same engine can power PDF, PNG, and standalone HTML freezing workflows

## Export generation model

- Base report generation still produces the canonical snapshot artifacts.
- Exports are generated on demand and then cached.
- Cache key should include:
  - `snapshot_id`
  - `presentation_hash`
  - export format
  - export options hash

Recommended output storage:

- reuse artifact storage directory under a per-report/per-snapshot structure
- store metadata in DB for lookup, ownership, and expiry

## GitHub publishing model

- Use a GitHub App for profile README publishing.
- Do not use a broad OAuth write scope for publishing.
- Default safe path:
  - user manually creates their profile repo (`username/username`) if missing
  - user installs the GitHub App on that repo only
  - app fetches existing README, shows diff, then updates `README.md` on explicit confirmation

Important constraint:

- GitHub does not offer a permission limited only to a profile README.
- The closest safe model is GitHub App installation on one selected repository with `Contents: write`.

## Data Model Additions

### Export records

Add a new persistence model for export jobs and produced artifacts.

Suggested fields:

- `id`
- `report_id`
- `snapshot_id`
- `owner_user_id`
- `export_type` (`pdf`, `png`, `html`, `markdown`)
- `status` (`queued`, `running`, `succeeded`, `failed`, `expired`)
- `presentation_hash`
- `options_json`
- `artifact_path`
- `mime_type`
- `byte_size`
- `error_message`
- `created_at`
- `updated_at`
- `completed_at`
- `expires_at`

### Markdown drafts

Either store markdown drafts as export records or add a small draft model.

Suggested draft fields:

- `id`
- `report_id`
- `owner_user_id`
- `preset_key`
- `markdown_body`
- `config_json`
- `created_at`
- `updated_at`

### GitHub publish connection state

If adding in-app publish later, persist minimal GitHub App linkage state.

Suggested fields:

- `user_id`
- `github_login`
- `profile_repo_owner`
- `profile_repo_name`
- `app_installation_id`
- `last_publish_commit_sha`
- `last_publish_at`

Do not store long-lived personal access tokens.

## API Surface

### Export endpoints

- `POST /api/reports/{report_id}/exports`
  - create export job
  - body includes `exportType` and options
- `GET /api/reports/{report_id}/exports`
  - list export jobs/artifacts
- `GET /api/reports/{report_id}/exports/{export_id}`
  - export status/details
- `GET /api/reports/{report_id}/exports/{export_id}/download`
  - secure artifact download

### Markdown endpoints

- `POST /api/reports/{report_id}/markdown`
  - generate or refresh markdown draft
- `GET /api/reports/{report_id}/markdown`
  - fetch current markdown draft
- `POST /api/reports/{report_id}/markdown/preview`
  - return rendered HTML preview of markdown if desired

### GitHub profile publishing endpoints

- `GET /api/github/profile-readme/status`
  - show whether user has linked install/repo
- `POST /api/github/profile-readme/connect`
  - begin GitHub App install/connect flow
- `GET /api/github/profile-readme/current`
  - fetch current profile README metadata/content
- `POST /api/reports/{report_id}/profile-readme/diff`
  - compare generated markdown against current README
- `POST /api/reports/{report_id}/profile-readme/publish`
  - publish on explicit confirmation

## UI Surfaces

### Report detail page

Add an export panel on `ghstats/templates/web/report_detail.html.j2`.

Owner-facing capabilities:

- export buttons for PDF, PNG, standalone HTML, and Markdown
- loading/progress state for queued/running exports
- download links for completed artifacts
- markdown preset chooser
- copy/download markdown
- later: "Publish to GitHub profile" CTA for connected users

### Markdown composer surface

Requirements:

- preset switcher (`profile_readme`, `summary_markdown`)
- section toggles
- optional text slots for heading/tagline/CTA copy
- side-by-side raw markdown and preview
- clear note that GitHub rendering may differ slightly from app preview

### GitHub publish UX

Requirements:

- explain permissions clearly
- show target repo name explicitly
- show current README state if found
- show unified diff before publish
- require explicit confirm action
- surface failures like branch protection, missing repo, or denied app install clearly

## Markdown Product Design

### Preset: `profile_readme`

Purpose:

- optimized for the special GitHub profile repository
- concise, skimmable, personality-forward

Suggested sections:

- intro / headline
- key stats bullets
- top repositories
- recent activity summary
- language snapshot
- optional link to full hosted report

Style rules:

- compact by default
- avoid tables on mobile-first profile views unless clearly beneficial
- allow tasteful emoji/icons but keep them optional
- no raw HTML required in phase 1

### Preset: `summary_markdown`

Purpose:

- reusable summary for repo docs, portfolio pages, or notes

Suggested sections:

- report title
- period covered
- key metrics
- highlights
- top repos
- links

## Export Runtime Requirements

### Browser worker

- run Playwright/Chromium in a dedicated service or worker container
- set strict timeout per export job
- bound concurrency to avoid overwhelming the host
- include required system fonts/libs in Docker

### Network policy

- export rendering should not browse arbitrary URLs
- prefer rendering from local trusted HTML/content
- avoid depending on live CDN fetches during export

### Chart handling

- current report themes rely on Chart.js
- for PDF/PNG, browser execution can render charts normally before capture
- for standalone HTML, freeze charts into self-contained form:
  - either inline Chart.js locally and inline config data
  - or replace charts with rendered images/data URLs before save

Recommended phase 1 path:

- let browser render charts for PDF/PNG
- freeze charts to images for standalone HTML to maximize portability

## Concurrency and Caching Rules

- exports are derived from immutable snapshot + presentation config
- a running export job must never mutate canonical report snapshot data
- if a newer snapshot appears, older export artifacts remain tied to the older snapshot and are not silently relabeled
- presentation changes should invalidate only matching export caches, not the underlying report snapshot

## Validation and Hardening Rules

- export type must be allowlisted
- options must be schema-validated and bounded
- file downloads must verify ownership/visibility
- markdown text overrides must be plain text only
- no arbitrary remote image URLs should be introduced by user-provided markdown fields in phase 1
- GitHub publish must target only the exact configured profile repository
- publish flow must show diff and require explicit confirmation

## Rollout Plan

### Phase 1: export foundation

- add export job model and artifact metadata
- add Playwright/Chromium worker path
- add PDF and PNG export endpoints + owner UI
- cache artifacts and enforce auth checks

### Phase 2: standalone HTML export

- freeze report into portable single-file HTML
- remove external asset dependence from exported artifact
- add download flow and storage cleanup behavior

### Phase 3: markdown export

- add markdown presets and preview UI
- support copy/download workflows
- support links back to hosted report

### Phase 4: GitHub profile publishing

- add GitHub App integration
- add install/connect flow
- add current README fetch + diff preview
- add explicit publish action

## Acceptance Criteria

- owner can generate PDF export from a report detail page
- owner can generate PNG export from a report detail page
- owner can download a portable single-file HTML artifact that works without remote dependencies
- owner can generate markdown from report data using at least two presets
- markdown output is previewable and downloadable/copyable
- exports are derived from immutable snapshots, not live GitHub refetches
- private reports remain private in all export/download paths
- export jobs are bounded, observable, and failure-reporting
- if GitHub profile publishing is enabled, the app uses GitHub App repo-scoped installation, not broad OAuth write scopes
- publish flow previews the resulting README diff before committing changes

## Known Constraints

- there is no GitHub permission limited only to profile README updates
- very tall reports may make PNG export expensive or impractical
- GitHub profile README rendering differs slightly from generic markdown preview in some cases
- branch protection or repo rules may block direct publish writes

## Recommended Defaults

- start with on-demand export generation rather than precomputing every derivative
- use PDF as the recommended long-form export
- use PNG for quick-share only
- keep standalone HTML export portable and frozen
- make GitHub publishing opt-in and explicit, with manual profile repo setup as the default low-risk path
