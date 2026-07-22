# Changelog

## Unreleased

- Raised the minimum supported versions of cryptography, MCP, Pydantic, PyJWT,
  pytest, python-dotenv and python-multipart to releases containing published
  security fixes; the lockfile already resolves to versions at or above these
  floors.
- Centralized validation for user, scenario, agent, run and dataset path components.
- Replaced bulk ZIP extraction with bounded, traversal-safe extraction that rejects
  symlinks, special files and oversized expanded archives.
- Stopped archive review endpoints from following local filesystem paths stored in
  run manifests.
- Required deployment-managed JWT and Fernet secrets instead of generating and
  writing authentication secrets to local files.
- Removed tainted WebSocket values from console format strings and added security
  boundary regression tests to CI.

## v0.1.11 — 2026-07-22

- Added the professional capital-market evaluation scenario and its complete
  English locale overlay.
- Completed bilingual viewer, operator console, archive, model-analysis,
  training-data and user-management presentation.
- Made locale switching non-disruptive: the active evaluation keeps its state,
  while the next reset adopts the selected Agent language.
- Added an automated authenticated-UI localization contract test.
- Corrected the documented public-repository scope to match the local
  authentication, viewer and operator-console code that is now included.
- Restricted GitHub Actions token permissions, pinned third-party Actions to
  immutable commits and added weekly Dependabot updates.

## World Adapter architecture — 2026-07-21

- Aligned the public capital-market scenario core at scenario version `0.2.1`.
- Tightened order-price identity validation to the canonical 8% tolerance.
- Corrected rendering so submitted orders are not presented as filled before settlement.
- Added a unified World Adapter contract for rule-based, algorithmic, learned,
  simulator, reality-connected and hybrid world models.
- Separated world execution from the four settlement-authority modes so any
  settlement route may consume adapter transitions without granting the
  adapter automatic scoring authority.
- Added provenance and assurance contracts for model identity, confidence,
  validation evidence, assumptions and limitations.
- Added an optional Grid2Op adapter, deterministic reference adapter, smoke
  test and public SDK documentation.
- Updated the product positioning around giving domain experts a reusable AI
  framework instead of requiring a complete physical simulator.

## v0.1.5 — 2026-07-18

- Audited and repaired public Markdown links (clean audit: 0 missing internal links).
- Published the public candidate scope and qualified-lead log template.
- Added permission-aware community distribution targets and targeted outreach drafts.
- Improved macOS/Linux and Windows installer diagnostics, including explicit Python interpreter selection.
- Linked the public technical discussion from the English and Chinese README paths.

## v0.1.4 — 2026-07-18

- Published the design-partner pilot path with scope, acceptance criteria, and starting price.
- Added bilingual founder outreach messages and an auditable outreach queue.
- Added the public design-partner call and linked it from the README, founder profile, and launch content.
- Created the public release `v0.1.4` for this adoption and pilot milestone.

## v0.1.3 — public preview

- Added deterministic no-key Market Replay with evidence-linked settlement.
- Added default-deny public export manifest and candidate preparation tooling.
- Isolated authentication storage behind a hosting adapter in the generic engine.
- Excluded private scenarios, commercial control-plane routes and operator viewer from the public candidate.

TraceArena remains a public preview. Release notes do not claim customer adoption, revenue, model performance, investment returns, or business outcomes.
