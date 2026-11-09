# Agent Office

Four agents, one office. The **Agent Office** is the admin's home page: you watch the agents work, see what each one is
doing, and jump to LLM performance. Customers only ever see the support chat.

## Who sees what

| Person | Sees | How |
|---|---|---|
| **Admin** (you, the only one) | The Agent Office first, then LLM performance, Infrastructure and CI/CD when needed | Sign in at `:8200`; the "Admin console" menu (bottom left) opens the other apps already signed in |
| **Customer** | Only the support chat, with no navigation, model picker or internal details | Sign up / sign in at `:8000` |

The admin is whoever is listed in `ADMIN_EMAILS` in `multiagent/.env` (currently one address), and in Supabase also
in the `admins` table created by the migration. In real Supabase mode the address must also be **email-confirmed**, so
nobody can sign up as the admin. Every admin route returns 403 to anyone else; the apps' pages show "Admins only".

The Infrastructure and CI/CD agents work in the background. CI/CD can be started without opening its UI: set
`CICD_WEBHOOK_TOKEN` and have a git hook call `POST :8300/api/webhook/change` (header `X-Webhook-Token`, body
`{"repo_path": "...", "base": "HEAD~1", "head": "HEAD"}`). The review appears in the admin console and waits for approval.

Each agent is a team of colleagues you can watch working in the **office visualization**
(`office/`), and each has its own backend and UI built on one shared kit.

| Team | Folder | Port | What it does |
|---|---|---|---|
| Support | `repo-support-bot` | 8000 | Streaming support chat, tool calling, generative UI, voice in (Gemini) and out (browser/Edge) |
| Infrastructure | `repo-iac-agent` | 8100 | Turns a conversation into Terraform for **any** cloud; plan, approve, apply |
| CI/CD | `repo-cicd-agent` | 8300 | LLM review, human approves the *summary*, then tests, scans, build, rollout |
| LLM performance | `repo-meta-observability` | 8400 | Latency, tokens, cost, errors, evals (LLM-as-judge), LangSmith traces, service health |
| Office | `repo-office/office` | 8200 | The animated office. Unchanged design; teams and members come from `hub/roster.py` |

There is no separate TTS agent: speech-to-text is Gemini 3.5 Flash (via OpenRouter) and text-to-speech is the browser's
own voices (Edge neural voices when available).

## Run everything

```bash
pip install -r repo-support-bot/support-bot/requirements.txt -r repo-iac-agent/iac-agent/api-requirements.txt locust
python repo-office/shared/run_all.py             # real Supabase sign-in, real models; opens the admin console
python repo-office/shared/run_all.py --dev-auth  # local only: sign-in offers "Continue as admin" and "Continue as a customer"
python repo-office/shared/run_all.py --stub      # canned model replies, spends no credits (load tests)
```

Secrets live in **`multiagent/.env`** (outside every repo, never committed): OpenRouter, Supabase, Redis, LangSmith.
Every service finds it by walking up from its folder. `.env.example` in each repo lists the variables.

## Shared pieces (`shared/`, copied into each repo by `python shared/sync.py`)

- `agentkit/` Python: OpenRouter models with automatic fallback (GPT 6.1 Sol <-> Claude Sonnet 5.5), Supabase auth
  (the browser's token is validated by Supabase and forwarded so row level security applies), a store that uses Supabase
  or SQLite, a cache that uses Redis or memory, LangSmith tracing, per-call telemetry, the generative-UI schema.
- `ui/` the "Aurora" theme and components every app uses: ripple buttons, spring toggles, gradient-beam composer,
  sliding-number counters, animated SVG icons, mood-reactive background, confetti, charts, and the block renderer
  that turns a model's `<ui>{...}</ui>` payload into cards, steps, tables, charts, stats, code and checklists.
- `supabase/0001_init.sql` the database schema with row level security.

## Observability, drift and auto-heal (the heart of the platform)

- **Platform tab**: real CPU, memory, disk, request rate, p95 latency, error rate, event-loop lag and uptime for every service (each service pushes APM samples every 10 s; Observability also probes `/health`). Incidents carry a "what to do" line and a "needs you" flag when a person must act.
- **Delivery tab**: watches CI/CD runs. A failure that looks transient (timeouts, resets, 502/503, rate limits) is re-run automatically, at most twice, with back-off. Code, config and leaked-secret failures are never retried: they become a "needs you" item with the exact fix.
- **Drift tab**: every applied IaC stack is registered; Observability asks the IaC agent to run `terraform plan`, scores each change by risk and only remediates after the admin approves. Without Terraform installed the check says "cannot check" and tells you what to install.
- **Dashboards tab**: built-in dashboards plus a designer. Describe what you want; it asks every question it needs at once (service, audience, range, thresholds), then builds a dashboard using only metrics that exist in the catalog.
- **Agent Office conversations**: each cabin has a talk panel. Teams ask all their questions first (click the suggested answers, press Send once), then start work. Anything only you can fix appears as a "Needs you" card, both in the office panel and in the team's own app.
- **Infrastructure agent**: the *Architecture* button draws the design (cloud, region, network, components and flows) with zoom, pan and SVG download. Open a session first.

## Before real sign-in: create the Supabase tables and the admin account

1. Create the tables (below). 2. Open the Agent Office, **create an account with the admin email** (the one in `ADMIN_EMAILS`),
confirm the email, and sign in. Change the admin address in `.env` and in the `admins` table if it should be someone else.

### Supabase tables

The Supabase publishable key cannot create tables, so until you do this the apps run on a local SQLite file
(`data/agent.db`) and say so in `/health`. In the Supabase dashboard open **SQL Editor -> New query**, paste
`shared/supabase/0001_init.sql`, and run it. On the next start every service switches to Supabase by itself.
Sign-up requires email confirmation (leave Supabase's auto-confirm off), which is the safe default.

## Redis

Set `REDIS_URL` in `.env` to share the rate limiter and cache across workers. If it is empty or unreachable, the services
fall back to an in-process cache and rate limiter (limits are then per server process, so with several workers you want Redis).

## Tests

```bash
python -m pytest repo-office/shared/tests                       # kit
python -m pytest repo-support-bot/support-bot/tests            # 14 tests
python -m pytest repo-office/office/tests                      # 5 tests (hub access control)
python -m pytest repo-iac-agent/iac-agent/tests                # 20 tests
python -m pytest repo-cicd-agent/cicd-agent/tests              # 12 tests
python -m pytest repo-meta-observability/meta-observability/tests  # 10 tests
```
They run offline with the stub model, dev auth and a throwaway database.

## Load tests

```bash
python repo-office/shared/run_all.py --dev-auth --stub
python repo-office/shared/run_loadtest.py support --users 150 --rate 25 --time 50s
python repo-office/shared/run_loadtest.py perf --users 100 --rate 25 --time 40s
python repo-support-bot/support-bot/loadtest/live_smoke.py --base http://127.0.0.1:8020 --chats 12   # real models, costs cents
```
Reports land in `repo-meta-observability/.../data/loadtests` and show on the Performance panel's Services tab.
Telemetry sent by the ingest load test is tagged `loadtest` and hidden from the dashboard.

## Safety notes

- Services report into the office and the performance panel with `INGEST_TOKEN` (random value in `.env`); the office refuses events without it.
- `AUTH_MODE=dev` accepts forged tokens. It exists for local tests only; never set it on a deployed machine.
- Cloud credentials for Terraform are read from the environment of the process that runs plan/apply. The model never sees them.
- Nothing is applied without an explicit human approval and a second confirmation. Secrets found in a change block approval.
