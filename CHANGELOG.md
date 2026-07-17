# Changelog

## v0.1.3 — 2026-07-17

- Added the localhost-only self-hosted Demo Console with scenario language, model/provider configuration, temporary in-memory API-key input, run state, and audit timeline.
- Added Docker Compose startup bound to `127.0.0.1` and Demo API smoke coverage.

## v0.1.2 — 2026-07-17

- Added a dependency-free public Replay Viewer with English/Simplified-Chinese switching and offline artifact loading.
- Added presentation-only scenario locale packs and the capital-market `en-US` pack.
- Added `scenario_locale` runtime configuration and locale regression coverage.
- Fixed the declared order-rejection render effect reference.

## v0.1.1 — 2026-07-17

- Added English and Simplified Chinese navigation for public documentation and community policies.
- Added a locale contract and bilingual Market Replay documentation.
- Added `--locale en-US|zh-CN` to Market Replay; the selected locale is recorded in the run manifest.
- Added bilingual synthetic replay action rationale and Chinese-output regression coverage.

## v0.1.0 — 2026-07-17

- Added deterministic no-key Market Replay with evidence-linked settlement.
- Added default-deny public export manifest and candidate preparation tooling.
- Isolated authentication storage behind a hosting adapter in the generic engine.
- Excluded private scenarios, commercial control-plane routes and operator viewer from the public candidate.

This is the first public TraceArena release. GitHub Actions verifies the public runtime and no-key replay on Ubuntu and macOS.
