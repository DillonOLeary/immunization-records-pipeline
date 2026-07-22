# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A pipeline that relays immunization records from MIIC (Minnesota's registry,
via the AISR bulk interface) to Infinite Campus for school districts, on a
schedule, with delivery through Google Drive. Student health data flows
through this system: never put PHI in code, tests, logs, or commits.

Read ARCHITECTURE.md before structural changes. It contains the target
design, the build-order phases, and a live progress checklist. Keep the
progress section current as work lands.

## Layout

Single uv project. `src/mn_immunization/` holds the package in vertical
slices: `etl/` (legacy transform pipeline, replaced in phase 2), `sources/aisr/`
(MIIC protocol client), `runtime/` (CLI, cloud handlers, composition).
`mock/` is a workspace member with a fake AISR server. `infra/` is Terraform.
`tests/` mirrors the slices.

## Commands

```sh
uv sync                          # install everything (incl. mock, dev deps)
uv run pytest                    # full test suite
uv run ruff check src tests mock # lint
uv run mn-immunization --config <cfg> transform|bulk-query|get-vaccinations
uv run mock-server               # local fake AISR
```

## Rules

- No PHI anywhere in the repo or its logs. Logs carry counts, hashes, school
  names, and error classes only.
- Production deploys happen from CI, never by hand.
- Each rewrite phase leaves production working; see ARCHITECTURE.md.
- The deployed Cloud Functions run from GCP project `mn-immun-bd9001` until
  the phase 5 cutover; do not assume this repo's Terraform matches the
  console until phase 4 reconciles them.
