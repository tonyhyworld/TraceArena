# Open-source sustainability paths

Updated: 2026-07-18

This page records public funding paths that may support TraceArena's open
benchmark and agent-evaluation work. It is a research note, not a claim that
TraceArena has been selected, funded, or endorsed by any organization.

## Highest-fit path: Open Benchmarks Grant

[Snorkel AI Open Benchmarks Grant](https://benchmarks.snorkel.ai/) is the
closest match to TraceArena's current direction. The program says it is backed
by a $3M commitment, funds open-source datasets, benchmarks, and evaluation
artifacts, and accepts applications on a rolling basis. Selected teams receive
expert data credits and publish the resulting open-source dataset or paper.

The strongest application would not ask for general product funding. It would
propose a concrete public benchmark built on TraceArena, for example:

- long-horizon incident-response decisions with an authoritative synthetic
  service state;
- replayable evidence → action → event → settlement traces;
- a published failure taxonomy and deterministic reference fixtures;
- a clear comparison protocol for models or agent runtimes.

Before applying, maintainers should have at least one external run, a stable
benchmark specification, and a short statement of what new evaluation signal
the benchmark measures.

## Possible company financing: GitHub Fund

[GitHub Fund](https://github.com/open-source/github-fund) describes an equity
investment program with M12 for pre-seed and seed open-source companies. It is
not a grant and is not a substitute for validating community adoption or a
paid pilot. It becomes relevant only after TraceArena has a company structure,
external users, and a credible commercial model.

## Do not pursue as an open call right now

- The [NGI Zero Commons Fund](https://nlnet.nl/commonsfund/index.html) page
  states that its thirteenth and final Commons call closed on June 1, 2026.
  Other NGI programs may exist, but this specific call is not open.
- The [Apache Responsible AI Initiative](https://news.apache.org/foundation/entry/the-apache-software-foundation-launches-10m-responsible-ai-initiative-with-initial-1-75m-donation)
  is described as support for ASF projects and communities. TraceArena is not
  an Apache project, so it should not be presented as an eligible applicant.

## Evidence required before any application

Record these facts rather than estimates:

1. at least one external developer run;
2. a reproducible benchmark or scenario fixture;
3. the exact research/evaluation question;
4. the open-source deliverable and license;
5. a budget tied to data, compute, maintenance, and publication;
6. any external feedback or collaboration already obtained.

Until those facts exist, the highest-return action remains obtaining the first
ten real runs and one qualified evaluation pilot.
