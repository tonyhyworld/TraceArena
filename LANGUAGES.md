# Language support

[English](LANGUAGES.md) | [简体中文](LANGUAGES.zh-CN.md)

TraceArena keeps one runtime and one scenario contract, rather than maintaining forked Chinese and English implementations. Language is a presentation and scenario-content concern; outcome rules, evidence, settlement and replay identifiers remain language-neutral.

## Supported public languages

| Surface | English (`en-US`) | Simplified Chinese (`zh-CN`) |
| --- | --- | --- |
| Root README and release information | Default | Available |
| Contribution and security guidance | Default | Available |
| No-key Market Replay CLI and summary | Default | `--locale zh-CN` |
| Synthetic replay action rationale | Available | Available |
| Capital-market scenario source package | English guide | Default source language |

The capital-market example deliberately keeps its canonical scenario declarations in Chinese for this release. Its IDs, structured values and settlement logic are locale-neutral. New public scenarios must declare their supported locales and provide translated user-facing text before claiming bilingual support.

## Locale contract

- Use BCP 47 locale tags, currently `en-US` and `zh-CN`.
- Keep IDs, action types, metrics, trace fields and fixture schema language-neutral.
- Localize user-visible labels, prompts, summaries, help text and documentation.
- Do not translate evidence IDs, hashes, provider IDs, symbols or settlement outcomes.

Report translation gaps as an issue with the `i18n` label.
