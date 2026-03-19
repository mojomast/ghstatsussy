# Export And Profile Publishing Implementation Notes

This document summarizes the implemented export and GitHub profile publishing flow added after `docs/export-and-profile-publishing-spec.md` and `docs/export-and-profile-publishing-handoff.md`.

## What shipped

- export persistence in `report_exports`
- export job payload support in `report_jobs`
- PDF export via Playwright + Chromium
- PNG export via Playwright + Chromium with tall-page guard
- standalone HTML export with frozen canvas charts and stripped remote runtime dependencies
- markdown export with `profile_readme` and `summary_markdown` presets
- owner report detail UI for export queueing, markdown preview, and GitHub profile publishing
- GitHub profile README connect/diff/publish endpoints using a repo-scoped GitHub App model

## Snapshot-first behavior

- exports resolve from stored `render_document.json` plus saved `presentation_config`
- export generation does not rerun analytics and does not refetch live GitHub data
- export cache reuse keys off report, snapshot, export type, presentation hash, and normalized options
- private report exports remain owner-only downloads

## Runtime requirements

- install Python deps from `requirements.txt`
- install Playwright Chromium with:

```bash
python -m playwright install chromium
```

- Docker image now installs Chromium runtime libraries and Playwright browser binaries

## GitHub profile publishing model

- publishing does not use broad OAuth write scopes
- use GitHub OAuth only for hosted sign-in and report generation
- use a GitHub App with repo-scoped installation on `username/username`
- flow is: connect repo/install metadata -> fetch current README -> preview unified diff -> explicit publish confirmation
- PAT storage remains disallowed

## Current limitations

- standalone HTML strips remote font imports rather than embedding font files
- preview mode stubs binary export downloads instead of generating actual PDF/PNG artifacts
- GitHub App install URL generation expects the app slug and directs the user to install on the profile repo manually
