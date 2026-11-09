"""
Load test for the support API.

    locust -f loadtest/locustfile.py --host http://127.0.0.1:8000 --headless -u 50 -r 10 -t 60s

Needs the service in dev auth mode (AUTH_MODE=dev). Use LLM_MODE=stub to test our own stack without spending credits,
or leave the live models on for a short, small run. Each simulated user is a distinct signed-in user.
Chat requests are only counted as successful when the stream really finishes with a `done` event; time to the first
streamed token is reported separately as "chat: first token".
"""

import itertools
import json
import time

from locust import HttpUser, between, events, task

_ids = itertools.count(1)
PROMPTS = ["Where is my order 4412?", "Is order 9001 delayed?", "What can you help me with?", "I need a human agent", "Status of order 5120 please"]


class SupportUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        self.n = next(_ids)
        self.h = {"Authorization": f"Bearer dev:load{self.n}@example.com"}
        self.conv = None

    @task(6)
    def chat(self):
        t0 = time.perf_counter()
        body = {"message": PROMPTS[self.n % len(PROMPTS)], "model": "primary"}
        if self.conv:
            body["conversation_id"] = self.conv
        first = None
        done = False
        with self.client.post("/api/chat", json=body, headers=self.h, stream=True, catch_response=True, name="chat (response headers)") as r:
            if r.status_code != 200:
                return r.failure(f"HTTP {r.status_code}")
            for line in r.iter_lines():
                if not line.startswith(b"data:"):
                    continue
                ev = json.loads(line[5:])
                if ev["type"] == "meta":
                    self.conv = ev["conversation_id"]
                elif ev["type"] == "token" and first is None:
                    first = (time.perf_counter() - t0) * 1000
                elif ev["type"] == "done":
                    done = True
                elif ev["type"] == "error":
                    return r.failure("stream error event")
            r.success() if done else r.failure("stream ended without done")
        if done:
            events.request.fire(request_type="SSE", name="chat: complete stream", response_time=(time.perf_counter() - t0) * 1000, response_length=0, exception=None, context={})
        if first is not None:
            events.request.fire(request_type="SSE", name="chat: first token", response_time=first, response_length=0, exception=None, context={})

    @task(2)
    def list_conversations(self):
        self.client.get("/api/conversations", headers=self.h, name="list conversations")

    @task(1)
    def open_conversation(self):
        if self.conv:
            self.client.get(f"/api/conversations/{self.conv}", headers=self.h, name="open conversation")

    @task(1)
    def unauthenticated_is_rejected(self):
        with self.client.get("/api/conversations", name="no auth -> 401", catch_response=True) as r:
            r.success() if r.status_code == 401 else r.failure(f"expected 401, got {r.status_code}")

    @task(1)
    def health(self):
        self.client.get("/health", name="health")
