Run tests and integration helpers

- `run_unit_tests.sh` — runs unit tests located under `tests/unit`
- `run_integration.sh` — brings up `docker compose` stack, waits for app `/health`, runs integration tests, then tears down
