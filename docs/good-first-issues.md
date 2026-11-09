# Starter tasks

Each section below is one issue, ready to file. Run `python scripts/seed_issues.py` (needs the GitHub CLI and `gh auth login`) to create the labels and all of these as issues in one go.
Every task lists where to look and what "done" means. All of them can be built and tested with no API keys.

## Add example prompts for more clouds
labels: good first issue, area:iac
The Infrastructure agent shows one-click example prompts on its welcome screen. Add examples for clouds that have Terraform providers, such as Scaleway, OVHcloud, Vultr, Linode (Akamai), Cloudflare or Exoscale.

**Where:** `EXAMPLES` in `repo-iac-agent/iac-agent/api/sessions.py`.

**Done when:** at least three new examples appear on the welcome screen, and `tests/test_api.py::test_examples_cover_several_clouds` is extended to cover them.

## Add a built-in dashboard
labels: good first issue, area:observability
Built-in dashboards are plain data. Add one, for example "Support chat" (request rate, p95 latency and error rate for the support service) or "Cost by agent".

**Where:** `BUILTIN` in `repo-meta-observability/meta-observability/app/dashboards.py`; metric keys are in `CATALOG` in `app/engine.py`.

**Done when:** the dashboard renders with data in the Dashboards tab, and a test in `tests/test_observability_engine.py` renders it without errors.

## Add a new metric to the catalog
labels: good first issue, area:observability
Add a metric the dashboard designer can use, for example requests per route, or the share of 4xx responses.

**Where:** `CATALOG` and the query functions in `repo-meta-observability/meta-observability/app/engine.py`.

**Done when:** the metric can be queried and validated, appears in the designer's allowed list, and has a unit test.

## Recognise more transient CI failures
labels: good first issue, area:cicd
Auto-heal retries only failures that look transient. Add more signatures (DNS hiccups, registry 5xx, `EAI_AGAIN`, "TLS handshake timeout") without ever matching real test failures.

**Where:** the transient pattern and `classify_failure` in `repo-cicd-agent/cicd-agent/app/runs.py`.

**Done when:** `tests/test_cicd_heal.py` has a passing case for each new signature **and** a negative case showing that an assertion failure which mentions a timeout is still classified as `code`.

## Fix label truncation in the architecture diagram
labels: good first issue, area:iac, frontend
Long component names are cut off in the node boxes ("application func..."). Wrap or shrink labels so names stay readable.

**Where:** `repo-iac-agent/iac-agent/frontend/diagram.js` (and `iac.css`).

**Done when:** the Architecture modal shows readable labels for a design with long names, shown in a screenshot attached to the PR.

## Add a Docker Compose file
labels: help wanted, area:devx
One command to run everything: `docker compose up`. Five services plus a shared `.env`, with the `--dev-auth --stub` mode as the default so it works with no keys.

**Where:** new `Dockerfile` and `docker-compose.yml` at the repo root; ports are listed in `repo-office/shared/run_all.py`.

**Done when:** a fresh clone reaches the Agent Office at `localhost:8200` using only `docker compose up`.

## Add lint and format config
labels: good first issue, area:devx
Add a `ruff` config, a pre-commit file, and a lint step in `.github/workflows/tests.yml`. Do not reformat the whole codebase in the same PR.

**Done when:** `ruff check` passes in CI.

## Refuse the default service token outside dev mode
labels: help wanted, area:security
If `INGEST_TOKEN` is not set, the services fall back to a built-in default. Make non-dev runs refuse to start (or generate a random token and log a warning) instead.

**Where:** `repo-office/shared/agentkit/settings.py`, then run `python repo-office/shared/sync.py`.

**Done when:** starting without `INGEST_TOKEN` and without `--dev-auth` fails with a clear message, and a test covers it.

## Add sample diagrams for the attach feature
labels: good first issue, area:iac, docs
Add three to five sample architecture diagrams (PNG, PDF, draw.io, Mermaid) under `docs/samples/`, each with a short note on what it should produce.

**Where:** `docs/samples/`; the reading code is in `repo-iac-agent/iac-agent/app/provisioner/documents.py`.

**Done when:** each sample is read without error by `documents.extract`, with a test that loops over the folder.
