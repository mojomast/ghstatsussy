# Export And Profile Publishing Handoff

This handoff is for the next agent implementing report exports and GitHub profile README publishing.

Read `docs/export-and-profile-publishing-spec.md` first. Treat that file as the product and architecture source of truth.

## What has already been decided

1. Use Playwright + Chromium for visual exports.
2. Support four outputs:
   - PDF
   - PNG
   - standalone single-file HTML
   - markdown
3. Generate exports from stored report snapshots/presentation state, not from live GitHub refetches.
4. Use a GitHub App, not broad OAuth write scopes, for profile README publishing.
5. Do not pretend GitHub has a README-only permission. It does not.

## Implementation order

Follow this order unless you find a repo constraint that makes a step impossible.

### Phase 1: export foundation

- inspect current hosted job/report flow in:
  - `ghstats/web/jobs.py`
  - `ghstats/web/service.py`
  - `ghstats/web/models.py`
  - `ghstats/web/database.py`
- add persistence for export jobs/artifacts
- add internal service layer for export creation and lookup
- add Playwright-based export worker path
- implement PDF export first
- implement PNG export second
- wire owner-facing export controls into `ghstats/templates/web/report_detail.html.j2`

### Phase 2: standalone HTML export

- inspect current report rendering dependencies in:
  - `ghstats/render/html.py`
  - `ghstats/templates/report_base.html.j2`
  - theme templates under `ghstats/templates/`
- remove remote dependency assumptions from exported HTML
- freeze or inline chart output so the file is portable offline
- add standalone HTML download path

### Phase 3: markdown export

- create a markdown renderer from sanitized report data, not by scraping HTML
- start with two presets:
  - `profile_readme`
  - `summary_markdown`
- add markdown preview/copy/download UX to report detail page

### Phase 4: GitHub profile publishing

- implement GitHub App integration only after markdown export is solid
- support:
  - connect/install flow
  - profile repo detection
  - fetch current README
  - diff preview
  - explicit publish confirmation
- safest default: require user to create `username/username` manually if missing
- only consider automated repo creation after the safe path works

## Critical constraints

- Do not use broad OAuth write scopes like `public_repo` as the main publish solution.
- Do not render exports by fetching arbitrary public URLs.
- Do not rerun GitHub analytics just to export a different format.
- Do not expose private-report exports through public artifact URLs.
- Do not store PATs.
- Do not auto-publish README updates without a diff preview and explicit confirmation.

## Suggested code areas to add

- new package/module candidates:
  - `ghstats/export/browser.py`
  - `ghstats/export/service.py`
  - `ghstats/export/markdown.py`
  - `ghstats/web/github_app.py`
- likely hosted API additions in `ghstats/web/app.py`
- likely DB model additions in `ghstats/web/models.py`
- likely schema additions in `ghstats/web/schemas.py`

## UX guidance

- Keep export actions on the owner report detail page.
- Make progress visible for queued/running exports.
- Prefer simple action labels:
  - `Download PDF`
  - `Download PNG`
  - `Download HTML`
  - `Copy Markdown`
  - `Publish To GitHub Profile`
- Explain permission boundaries plainly in the profile publishing UI.

## Operational guidance

- Prefer a dedicated browser/export worker container over bloating the main web process.
- Add timeouts, size guards, and bounded concurrency.
- Expect very tall reports to be problematic for PNG; recommend PDF when needed.

## Validation checklist

Before handing off or merging, verify at minimum:

1. PDF export works for a normal public report.
2. PNG export works for a normal public report.
3. Private report exports require owner auth.
4. Standalone HTML opens locally without remote CDN dependency.
5. Markdown export works without scraping rendered HTML.
6. Markdown preset outputs are stable and readable.
7. Export generation does not refetch live GitHub data.
8. If GitHub publish is implemented, diff preview appears before write.
9. If GitHub publish is implemented, writes target only the configured profile repo.

## Recommended test commands

- run Python compile check:

```bash
./.venv/bin/python -m compileall ghstats
```

- run targeted app tests if added:

```bash
./.venv/bin/python -m pytest
```

- if Playwright is introduced, include exact install/bootstrap steps in Docker and local dev docs, then verify export generation from a local hosted report.

## Nice-to-have follow-ups, not required for phase 1

- JPEG/WebP social variants
- section-scoped image exports
- scheduled README republish
- PR-based publish mode for protected profile repos
- richer markdown presets for blogs/personal sites
