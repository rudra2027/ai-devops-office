"""
Load test for the performance service: telemetry ingest (what every agent hammers) plus dashboard reads.

    locust -f loadtest/locustfile.py --host http://127.0.0.1:8400 --headless -u 100 -r 20 -t 60s

Run the service with AUTH_MODE=dev. Ingest uses the shared ingest token (INGEST_TOKEN, default dev-ingest-token).
"""

import itertools
import os
import random

from locust import HttpUser, between, task

_ids = itertools.count(1)
TOKEN = os.environ.get("INGEST_TOKEN", "dev-ingest-token")


class Reporter(HttpUser):
    """An agent reporting LLM calls."""

    weight = 8
    wait_time = between(0.05, 0.3)

    @task(5)
    def ingest_one(self):
        self.client.post("/api/ingest", headers={"X-Ingest-Token": TOKEN}, name="ingest (1 call)", json={
            "agent": random.choice(["support", "iac", "cicd"]), "model": random.choice(["openai/gpt-6.1-sol", "anthropic/claude-sonnet-5.5"]),
            "latency_ms": random.randint(300, 9000), "input_tokens": random.randint(200, 3000), "output_tokens": random.randint(20, 800), "cost_usd": round(random.random() / 50, 5),
            "status": "ok" if random.random() > 0.03 else "error", "meta": {"loadtest": True}})

    @task(1)
    def ingest_batch(self):
        batch = [{"agent": "support", "model": "openai/gpt-6.1-sol", "latency_ms": random.randint(300, 4000), "input_tokens": 500, "output_tokens": 100, "cost_usd": 0.002, "meta": {"loadtest": True}} for _ in range(25)]
        self.client.post("/api/ingest", headers={"X-Ingest-Token": TOKEN}, json=batch, name="ingest (batch of 25)")


class DashboardViewer(HttpUser):
    """People watching the dashboard (it polls every 4 s)."""

    weight = 2
    wait_time = between(2, 4)

    def on_start(self):
        self.h = {"Authorization": f"Bearer dev:viewer{next(_ids)}@example.com"}

    @task(4)
    def overview(self):
        self.client.get("/api/overview?window=1h", headers=self.h, name="overview 1h")

    @task(1)
    def overview_day(self):
        self.client.get("/api/overview?window=24h", headers=self.h, name="overview 24h")

    @task(1)
    def services(self):
        self.client.get("/api/services", headers=self.h, name="services")
