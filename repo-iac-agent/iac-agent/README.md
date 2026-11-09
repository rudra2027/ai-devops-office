# iac-agent

Conversational infrastructure on **any cloud**. Four colleagues pass validated Pydantic objects along:
Rhea (`InfraRequirements`) -> Arjun (`ArchitecturePlan`, looks the cloud's terms up in the Terraform Registry through
tool calls) -> Tara (`GeneratedStack`, validated with `terraform validate` when installed, HCL syntax otherwise) ->
Rex (`ReviewReport`, plus deterministic secret/exposure checks the model cannot override).

- `api/` FastAPI on port 8100: `/iac/sessions...` (private per user, persisted), `/ops/findings` for drift findings
- `app/provisioner/` the pipeline, registry tools, plan/apply operator (apply needs approval and a saved plan)
- `app/` the original drift scan / policy / apply CLI (`python -m app.main scan`)
- `frontend/` chat, live "team at work" feed, blueprint panel, approvals

```bash
python -m uvicorn api.main:app --port 8100
python -m pytest tests
```
Without a `terraform` binary the plan step reports that plainly and you can download the generated files as a zip.
`_legacy/` holds the previous approval dashboard and routes.
