# TraceArena Research Paper Package

This directory contains the first public system-paper draft for TraceArena / AI World.

## Files

- [`ai-world-paper-en.md`](ai-world-paper-en.md): English system paper draft.
- [`ai-world-paper-zh-CN.md`](ai-world-paper-zh-CN.md): Chinese system paper draft.
- [`submission-notes.md`](submission-notes.md): reproducibility, authorship, and submission checklist.

## Scope and research status

This is a system paper, not a claim that TraceArena has solved every domain problem. The paper describes the implemented runtime, scenario-pack abstraction, multi-agent execution loop, world validation, settlement, traceability, and visual replay. Quantitative claims should only be added after the corresponding experiments are run and their artifacts are committed.

## Reproduce the system

The public repository contains runnable scenario-pack examples and local replay paths. Start with [`docs/quickstart.md`](../docs/quickstart.md), then inspect [`examples/scenario_pack_template`](../examples/scenario_pack_template) and [`examples/incident_response_world`](../examples/incident_response_world).
