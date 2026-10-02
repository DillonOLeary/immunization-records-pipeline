# CLAUDE.md

A pipeline that relays immunization records from MIIC (Minnesota's
registry, via AISR) to Infinite Campus for school districts, through
Google Drive. Student health data flows through it: never put PHI in code,
tests, logs, or commits.

Read ARCHITECTURE.md before structural changes and keep it true when a
change lands. Keep docs brief; delete stale docs rather than rewrite them
at length. History lives in commits and PR descriptions, not in files.

## Commands

```sh
uv sync                                    # everything, incl. the fake AISR
uv run pytest                              # all tests
uv run ruff check src tests mock           # lint
uv run ruff format --check src tests mock  # format gate
uv run basedpyright                        # types
uv run mock-server                         # local fake AISR
```

The pipeline runs as the Cloud Run Job `pipeline-job` (`run` opens a
period, `tick` advances it, `canary`, `refresh`); a manual run is
`gcloud run jobs execute`. The
`mn-immunization` CLI only reads the ledger.

## Rules

- No PHI in the repo or logs. Logs carry counts, hashes, school names, and
  error classes; never an exception message. `tests/test_architecture.py`
  enforces this and the dependency direction.
- Never rehearse `run`: every roster submission emails every nurse. Use
  `canary`.
- Deploys happen from CI on merge to `main`; Terraform is applied by a
  human. Live in GCP project `mn-immun-bd9001`, one project per district.
- A failed run is acceptable; leaked PHI and a headache for the nurses are
  not.
