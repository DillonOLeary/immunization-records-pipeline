# Minnesota Immunization Records Pipeline

Relays student immunization records from Minnesota's registry (MIIC, via
AISR) into files school staff import into Infinite Campus. It runs as a
Cloud Run Job per district; new records land in a Google Drive folder.

- [ARCHITECTURE.md](ARCHITECTURE.md): how it works and why.
- [ONBOARDING.md](ONBOARDING.md): standing up a district, and operating one.

## Development

```sh
uv sync                                  # package, dev tools, and the fake AISR
uv run pytest                            # all tests, including end-to-end
uv run ruff check src tests mock         # lint
uv run ruff format --check src tests mock
uv run basedpyright                      # types
uv run mock-server                       # the fake AISR on localhost:8080
uv run mn-immunization status --bucket <data-bucket>   # recent runs (read-only)
```

Real config, rosters, and records never live in this repo; production
reads them from the district's bucket.

## License

See [LICENSE](LICENSE).
