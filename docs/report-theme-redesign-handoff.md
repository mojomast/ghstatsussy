# Report Template Redesign Handoff

Current report presentation is tightly coupled to server-generated template HTML and theme tokens in `ghstats/render/html.py`, `ghstats/render/templates.py`, and `ghstats/render/themes.py`. Phase 1 should break that coupling.

## Design goals

- Remove the idea of site-wide UI theming; report styling applies only inside the report surface, not the dashboard/app shell.
- Make theme selection a per-report presentation setting (`presentation.themeKey`) that can change at runtime without report regeneration.
- Standardize report rendering around one shared section model so every supported feature is available in every theme.
- Support hardened customization for:
  - toggling allowlisted sections on/off
  - overriding selected allowlisted text slots
- Preserve current private/public guarantees:
  - no theme or customization path can expose raw or private-only data
  - public views only render sanitized, share-safe report content
- Keep each existing theme's visual identity, but reduce structural divergence so themes vary by layout/tokens, not by feature availability.

## Target architecture

- Backend later provides:
  - `renderDocument`: sanitized, presentation-agnostic report data
  - `presentationConfig`: theme key, section visibility, text overrides, section order if allowed
- Frontend owns:
  - one canonical report renderer
  - shared section components
  - theme token/layout system
  - owner-only customization UI
- Theme switching updates presentation only:
  - no analytics recompute
  - no HTML regeneration
  - no raw data fetch
- Themes should be implemented as:
  - CSS variables/tokens
  - layout presets
  - optional section-level style variants
- Avoid theme-specific feature logic; feature presence comes from the section contract, not from theme templates.

## Parallel workers and queue safety

- The final design must work correctly with multiple workers processing jobs in parallel.
- Theme switching and presentation updates must not depend on the async generation queue.
- Data generation and presentation updates must be separated so a running job cannot overwrite a newer theme/customization choice.

### Current queue constraints to account for

- Job claiming is not atomic today; multiple workers can claim the same queued job.
- The same report can have multiple queued or running jobs at once.
- Snapshot version assignment is race-prone under concurrent execution.
- Older jobs can overwrite newer report state on completion.

### Required concurrency rules for the redesign

- Treat generated report data as immutable snapshot state.
- Treat presentation config as mutable report/view state that is never owned by background workers.
- Theme changes, section toggles, and text overrides must apply without enqueueing a new report-generation job.
- If refresh/generation jobs run in parallel, publication must be deterministic:
  - either per-report serialization
  - or explicit supersession/version ownership rules
- Snapshot/cache publishing must use unique, collision-safe identifiers rather than inferred shared paths.
- Any cached HTML for a theme/presentation variant must be keyed by immutable snapshot id plus presentation hash.

### UX implications of worker separation

- Owner theme changes should feel immediate even while a refresh job is still running.
- If a newer data snapshot lands while a user is customizing presentation, the UI should preserve or clearly reconcile the saved presentation config.
- A running job may update available data sections, but it must not reset presentation choices unless the backend explicitly rejects invalid settings.

## Shared section contract

Use one canonical section inventory across all themes.

### Canonical sections

- `hero`
- `profile_summary`
- `key_stats`
- `timeline_commits`
- `timeline_loc`
- `activity_heatmap`
- `language_mix`
- `language_breakdown`
- `highlights`
- `repositories`
- `notes_and_warnings`
- `footer_meta`

### Section shape

Each section in `renderDocument.sections[]` should expose:

- `id`: stable section id from the canonical list
- `kind`: renderer type
- `enabledByDefault`: backend default visibility
- `available`: whether data exists and is safe to render
- `data`: sanitized payload needed by the section
- `textSlots`: allowlisted overrideable copy keys for that section
- `privacy`: share-safety classification for the section payload
- `emptyStatePolicy`: hide vs fallback copy

### Renderer rules

- Every theme must support every canonical section.
- Themes may reorder/group sections visually, but cannot drop support for a section.
- If a section is unavailable, all themes follow the same hide/fallback behavior.
- Section components accept only sanitized section data plus resolved presentation config.

## Theme parity work by template

### Baseline

- `default`: use as the parity reference implementation for all canonical sections and all interaction states.

### Existing templates

- `ledger`: preserve editorial rhythm, but support full chart, heatmap, language, notes, and repo coverage in the shared renderer.
- `transit`: keep route-map styling, but remove bespoke content assumptions so all standard sections fit the same contract.
- `archive`: keep exhibit framing while supporting the full shared section inventory and consistent empty states.
- `scrapbook`: keep collage energy, but normalize card/section wrappers so hidden/optional sections do not break layout.
- `orbital`: keep mission-control density while ensuring parity for notes, language breakdown, and repo rendering.
- `fieldnotes`: keep notebook styling, but support the same charting and warnings surfaces as other themes.
- `signalroom`: keep terminal/broadcast look, but render the same sections and owner customization affordances.
- `gallery`: keep poster asymmetry, but use shared section blocks instead of custom feature-specific DOM.
- `tapearchive`: keep modular archival styling, but render the full canonical section set with consistent toggles/fallbacks.

### Definition of parity

For each theme, parity means:

- all canonical sections render if `available=true`
- all section toggles behave consistently
- all allowlisted text overrides appear in the same slots
- loading, empty, warning, and private-safe states match shared rules
- no theme requires regeneration to apply presentation changes

## UX surfaces needed

### Owner-facing

- Report-level theme switcher in the report detail/viewer surface
- Presentation panel for:
  - theme selection
  - section visibility toggles
  - selected text overrides
  - reset to default presentation
- Live preview inside the report canvas
- Clear save/apply state for persisted presentation config
- Clear guardrails when a section is unavailable due to missing or sanitized data

### Public-facing

- Render resolved presentation only
- No edit controls
- No exposure of hidden or unavailable section metadata
- No indication of private-only content that was removed

### Shared UX behavior

- Theme change should feel instant and non-destructive
- Section toggles should preserve layout integrity across themes
- Copy override fields should show character limits and allowed fields only

## Hardening constraints

- Text overrides must be plain text only; no HTML, Markdown, CSS, JS, or arbitrary links.
- Only allowlisted `textSlots` can be overridden.
- Only allowlisted canonical sections can be hidden/shown.
- Theme keys must come from a fixed registry.
- Presentation config cannot request fields absent from the sanitized `renderDocument`.
- Public rendering must never infer hidden/private values from spacing, labels, counts, or fallback states.
- `include_private` safety remains unchanged:
  - reports containing private activity stay private
  - public/unlisted output must remain sanitized and share-safe
- Do not embed raw GitHub payloads client-side.
- Missing data behavior must be deterministic across themes.
- Customization failures should fail closed:
  - invalid theme -> default or rejected
  - invalid override key -> ignored/rejected
  - invalid section toggle -> ignored/rejected

## Phased implementation plan

### Phase 1: foundation and baseline runtime theming

- Define `renderDocument` and `presentationConfig` contracts
- Build one canonical report renderer with shared section components
- Implement runtime theme application on the report surface only
- Port `default` as the baseline parity theme
- Add owner-facing theme switcher and section toggle UI
- Add allowlisted text override support for a small initial set:
  - report title
  - hero eyebrow
  - hero title
  - hero copy
  - notes heading / footer label if needed
- Keep public/private behavior identical to current product rules
- Document the backend concurrency contract required for parallel workers before wider rollout

### Phase 2: full theme parity

- Port remaining themes onto the shared renderer
- Resolve theme-specific layout edge cases
- Add visual regression coverage across all themes and canonical sections
- Normalize empty/warning states and responsive behavior

### Phase 3: hardened customization expansion

- Expand overrideable text slots where product-approved
- Add persisted presentation config editing flows
- Add reset/versioning behavior for presentation changes
- Finalize owner/public UX polish and validation messaging

### Phase 4: rollout and cleanup

- Remove legacy per-template structural dependence
- Deprecate site-wide theming assumptions in report codepaths
- Reduce template sprawl and duplicate DOM/CSS paths
- Validate behavior under multi-worker concurrency before production rollout

## Acceptance criteria

- Changing `presentation.themeKey` updates the report theme without regeneration.
- The same sanitized `renderDocument` renders across all supported themes.
- Every theme supports the full canonical section inventory.
- Section visibility toggles work consistently and do not break layout.
- Allowlisted text overrides render safely and escape correctly.
- Public/private safety rules are unchanged from current behavior.
- Invalid presentation config is safely rejected or ignored.
- Owner edit controls never appear on public views.
- Responsive behavior is acceptable on desktop and mobile for every theme.
- Visual regression coverage exists for all themes against the shared section contract.
- Theme/presentation updates remain correct when multiple workers are active.
- A stale worker completion cannot overwrite newer presentation state.

## Phase 1 out of scope

- New analytics, new report sections, or changes to metric computation
- Arbitrary drag-and-drop layout builders
- Rich text/Markdown/custom HTML overrides
- User-authored CSS or custom theme creation
- Dashboard/site-shell redesign
- PDF/export/print-specific redesign
- Multi-report/global presentation presets
- Collaborative editing or approval workflows
- Changes to visibility policy, auth, or private-data rules

## Recommended implementation notes

- Treat theme as presentation only; treat section availability as data only.
- Prefer one report shell plus section partials/components over ten structurally unique templates.
- Keep the current ten theme identities, but express them through tokens/layout presets instead of bespoke feature DOM.
- Use the `default` theme as the golden parity target before porting the rest.
