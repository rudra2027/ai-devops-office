# meta-observability (LLM performance and evaluation)

- `POST /api/ingest` (header `X-Ingest-Token`) every agent reports each model call: latency, tokens, cost, status
- `GET /api/overview` KPIs, time series, per-agent and per-model tables (windows 1h, 24h, 7d)
- Evaluations: LLM-as-judge suites (`support_quality`, `iac_requirements`, `cicd_review`). The candidate model answers,
  the *other* model grades against a rubric, results are stored and compared.
- `GET /api/langsmith` recent traces from the `four-agent` project; `GET /api/services` health of every service
- The dashboard reads the newest 8,000 calls. For heavier volume, aggregate in Postgres instead.

```bash
python -m uvicorn app.main:app --port 8400
python -m pytest tests
locust -f loadtest/locustfile.py --host http://127.0.0.1:8400 --headless -u 100 -r 20 -t 40s
```
