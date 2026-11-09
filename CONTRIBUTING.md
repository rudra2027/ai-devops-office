# Contributing

Thanks for helping. The project is small enough to read in an afternoon, and every change is welcome: a new cloud example, a dashboard widget, a failure signature, a doc fix.

## Set up (2 minutes, no API keys)

```bash
git clone https://github.com/<you>/ai-devops-office.git && cd ai-devops-office
pip install -r requirements-dev.txt
python repo-office/shared/run_tests.py                 # every suite, stub LLM, no network
python repo-office/shared/run_all.py --dev-auth --stub # run the whole platform locally
```

## Ground rules

- **Tests with every change.** Suites live in each service's `tests/` folder and run with a stub LLM. Use a scripted fake model when you need to test agent logic (see `repo-iac-agent/iac-agent/tests/test_provisioner.py`).
- **The shared kit is edited once**, in `repo-office/shared`, then copied into each service: `python repo-office/shared/sync.py`. Do not edit the copies under `*/agentkit` or `*/frontend/kit` by hand.
- **Safety first.** Auto-heal may retry only transient failures. Anything that changes real infrastructure needs explicit human approval. Do not weaken either.
- **Never commit secrets** or a `.env`. Use `.env.example` for new settings. Tests must not need network access or API keys.
- **Keep prompts honest.** Agents must ask what they need up front, and anything only a person can fix must be shown to the user.
- Small, focused pull requests are easier to review. Describe what you changed and how you tested it.

## Finding something to work on

Look for [`good first issue`](https://github.com/rudra2027/ai-devops-office/labels/good%20first%20issue). The starter tasks, with the exact files to touch, are listed in [docs/good-first-issues.md](docs/good-first-issues.md).

## Reporting problems

Use the issue templates. For a security problem, please do not open a public issue; contact the maintainer privately through their GitHub profile.
