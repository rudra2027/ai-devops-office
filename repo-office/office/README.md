# Agent Office

Each agent is a **cabin** (team); each internal component of that agent is a
**colleague** at a desk. Every action the component takes (LLM call, tool call,
hand-off, error) is posted as a line in that colleague's message box, live.

```
hub/        FastAPI: POST /events, GET /stream (SSE), GET /roster, POST /demo/start
frontend/   The office UI, served by the hub at /
```

## Run

```bash
pip install -r requirements.txt
uvicorn hub.main:app --port 8200
```
Open http://localhost:8200. "Run demo" plays a scripted simulation (every line
is tagged DEMO). For real activity, set `OFFICE_URL=http://localhost:8200` in
the agent's `.env`; events are fire-and-forget and never block an agent.

`frontend/config.js` points the chat boxes at the IaC API (8100) and the
support bot (8000).

## Who sits where

Defined in `hub/roster.py`: IaC, Support, CI/CD and Observability (15 colleagues). There is no TTS team any more.
Every service reports into the hub through `agentkit/office.py` (set `OFFICE_URL`); the full stack is described in
`../README.md`. "Run demo" still plays a clearly marked simulation.

## IaC on any cloud

See `repo-iac-agent/iac-agent/app/provisioner/`: Rhea, Arjun, Tara and Rex pass
Pydantic objects (`InfraRequirements`, `ArchitecturePlan`, `GeneratedStack`,
`ReviewReport`). Cloud vocabulary is looked up at run time from the Terraform
Registry via tool calls, so no cloud is hard-coded. Plan/apply need a
`terraform` binary, cloud credentials in the environment, and a human approval.
