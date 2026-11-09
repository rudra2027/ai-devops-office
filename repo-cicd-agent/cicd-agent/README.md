# cicd-agent

Change review and delivery.

1. Submit a change: a sample, a pasted diff, or a local git repo under `CICD_ALLOWED_ROOTS`.
2. The reviewer (LLM) writes a plain-language summary, a risk level and findings. A deterministic secret scan runs too.
3. A human approves the summary. Secrets cannot be overridden; other blockers need an explicit override.
4. Stages run: tests (pytest or npm if present), security scan (secret scan; Trivy when installed), image build
   (only with `CICD_ENABLE_DOCKER=true`), rollout (needs `ARGOCD_SERVER`). Anything that cannot run is shown as
   **skipped with the reason**, never faked.
5. On failure an LLM diagnosis is attached as a suggestion for a human, and Telegram is notified if configured.

```bash
python -m uvicorn app.main:app --port 8300
python -m pytest tests
```
